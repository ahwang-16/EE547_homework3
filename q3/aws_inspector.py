import boto3
import json
import sys
import os
import argparse
from datetime import datetime
from botocore.exceptions import ClientError, NoCredentialsError, BotoCoreError
from botocore.config import Config

boto_config = Config(retries={'max_attempts': 1, 'mode': 'standard'})

def datetime_handler(x):
    if isinstance(x, datetime):
        return x.isoformat()
    raise TypeError("Unknown type")

def verify_auth_and_region(session, region):
    try:
        sts = session.client('sts', config=boto_config, region_name=region)
        identity = sts.get_caller_identity()

        if region:
            ec2 = session.client('ec2', config=boto_config, region_name='us-east-1')
            regions = [r['RegionName'] for r in ec2.describe_regions()['Regions']]
            if region not in regions:
                print(f"[ERROR] Invalid region: {region}", file=sys.stderr)
                sys.exit(1)

        return identity['Account'], identity['Arn']
    except (NoCredentialsError, ClientError) as e:
        print(f"[ERROR] Authentication failed: {str(e)}", file=sys.stderr)
        sys.exit(1)

def collect_iam_users(session):
    iam = session.client('iam', config=boto_config)
    users_data = []

    try:
        users = iam.list_users().get('Users', [])
        for u in users:
            user_info = {
                "username": u['UserName'],
                "user_id": u['UserId'],
                "arn": u['Arn'],
                "create_date": u['CreateDate'],
                "last_activity": u.get('PasswordLastUsed', None),
                "attached_policies": []
            }

            try:
                policies = iam.list_attached_user_policies(UserName=u['UserName']).get('AttachedPolicies', [])
                user_info["attached_policies"] = [
                    {"policy_name": p['PolicyName'], "policy_arn": p['PolicyArn']}
                    for p in policies
                ]
            except ClientError as e:
                print(f"[WARNING] Could not fetch policies for user {u['UserName']}: {e}", file=sys.stderr)

            users_data.append(user_info)
    except ClientError as e:
        if e.response['Error']['Code'] == 'AccessDenied':
            print("[WARNING] Access denied for IAM operations - skipping user enumeration", file=sys.stderr)
        else:
            print(f"[WARNING] IAM Error: {e}", file=sys.stderr)

    return users_data

def collect_ec2_instances(session, region):
    ec2 = session.client('ec2', config=boto_config, region_name=region)
    instances_data = []

    try:
        reservations = ec2.describe_instances().get('Reservations', [])
        for res in reservations:
            for inst in res.get('Instances', []):
                ami_id = inst.get('ImageId')
                ami_name = "Unknown"

                try:
                    images = ec2.describe_images(ImageIds=[ami_id]).get('Images', [])
                    if images:
                        ami_name = images[0].get('Name', 'Unknown')
                except ClientError:
                    pass

                tags = {t['Key']: t['Value'] for t in inst.get('Tags', [])}

                instances_data.append({
                    "instance_id": inst['InstanceId'],
                    "instance_type": inst['InstanceType'],
                    "state": inst['State']['Name'],
                    "public_ip": inst.get('PublicIpAddress', '-'),
                    "private_ip": inst.get('PrivateIpAddress', '-'),
                    "availability_zone": inst['Placement']['AvailabilityZone'],
                    "launch_time": inst['LaunchTime'],
                    "ami_id": ami_id,
                    "ami_name": ami_name,
                    "security_groups": [sg['GroupId'] for sg in inst.get('SecurityGroups', [])],
                    "tags": tags
                })
        if not instances_data:
            print(f"[WARNING] No EC2 instances found in {region}", file=sys.stderr)
    except ClientError as e:
        if e.response['Error']['Code'] == 'AccessDenied':
            print("[WARNING] Access denied for EC2 operations - skipping instances", file=sys.stderr)

    return instances_data

def collect_s3_buckets(session):
    s3 = session.client('s3', config=boto_config)
    buckets_data = []

    try:
        buckets = s3.list_buckets().get('Buckets', [])
        for b in buckets:
            name = b['Name']
            try:
                loc = s3.get_bucket_location(Bucket=name).get('LocationConstraint')
                bucket_region = loc if loc else 'us-east-1'

                paginator = s3.get_paginator('list_objects_v2')
                obj_count = 0
                size_bytes = 0

                for page in paginator.paginate(Bucket=name):
                    if 'Contents' in page:
                        obj_count += len(page['Contents'])
                        size_bytes += sum(obj['Size'] for obj in page['Contents'])

                buckets_data.append({
                    "bucket_name": name,
                    "creation_date": b['CreationDate'],
                    "region": bucket_region,
                    "object_count": obj_count,
                    "size_bytes": size_bytes
                })
            except ClientError as e:
                print(f"[ERROR] Failed to access S3 bucket '{name}': {e.response['Error']['Code']}", file=sys.stderr)
    except ClientError as e:
        print("[WARNING] Access denied for S3 operations - skipping bucket enumeration", file=sys.stderr)

    return buckets_data

def collect_security_groups(session, region):
    ec2 = session.client('ec2', config=boto_config, region_name=region)
    sg_data = []

    try:
        sgs = ec2.describe_security_groups().get('SecurityGroups', [])
        for sg in sgs:
            inbound = []
            for rule in sg.get('IpPermissions', []):
                protocol = rule.get('IpProtocol', 'all')
                from_port = rule.get('FromPort', 'all')
                to_port = rule.get('ToPort', 'all')
                port_range = f"{from_port}-{to_port}" if from_port != 'all' else 'all'

                for ip_range in rule.get('IpRanges', []):
                    inbound.append({
                        "protocol": protocol.replace('-1', 'all'),
                        "port_range": port_range,
                        "source": ip_range.get('CidrIp')
                    })

            outbound = []
            for rule in sg.get('IpPermissionsEgress', []):
                protocol = rule.get('IpProtocol', 'all')
                from_port = rule.get('FromPort', 'all')
                to_port = rule.get('ToPort', 'all')
                port_range = f"{from_port}-{to_port}" if from_port != 'all' else 'all'

                for ip_range in rule.get('IpRanges', []):
                    outbound.append({
                        "protocol": protocol.replace('-1', 'all'),
                        "port_range": port_range,
                        "destination": ip_range.get('CidrIp')
                    })

            sg_data.append({
                "group_id": sg['GroupId'],
                "group_name": sg['GroupName'],
                "description": sg.get('Description', ''),
                "vpc_id": sg.get('VpcId', '-'),
                "inbound_rules": inbound,
                "outbound_rules": outbound
            })
    except ClientError as e:
        print("[WARNING] Access denied for Security Group operations", file=sys.stderr)

    return sg_data

def print_table(data):
    acc = data['account_info']
    sm = data['summary']

    print(f"AWS Account: {acc['account_id']} ({acc['region']})")
    scan_dt = datetime.fromisoformat(acc['scan_timestamp'].replace('Z', '+00:00'))
    print(f"Scan Time: {scan_dt.strftime('%Y-%m-%d %H:%M:%S')} UTC\n")

    # IAM Users
    print(f"IAM USERS ({sm['total_users']} total)")
    print(f"{'Username':<20} {'Create Date':<20} {'Last Activity':<20} {'Policies'}")
    for u in data['resources']['iam_users']:
        cd = u['create_date'][:10] if u['create_date'] else 'N/A'
        la = u['last_activity'][:10] if u['last_activity'] else 'N/A'
        print(f"{u['username']:<20} {cd:<20} {la:<20} {len(u['attached_policies'])}")
    print()

    # EC2 Instances
    running_ec2 = sum(1 for i in data['resources']['ec2_instances'] if i['state'] == 'running')
    stopped_ec2 = sm['running_instances'] - running_ec2 # math fallback
    print(f"EC2 INSTANCES ({running_ec2} running, {len(data['resources']['ec2_instances']) - running_ec2} stopped)")
    print(f"{'Instance ID':<20} {'Type':<11} {'State':<10} {'Public IP':<15} {'Launch Time'}")
    for i in data['resources']['ec2_instances']:
        lt = i['launch_time'][:16].replace('T', ' ') if i['launch_time'] else 'N/A'
        print(f"{i['instance_id']:<20} {i['instance_type']:<11} {i['state']:<10} {i['public_ip']:<15} {lt}")
    print()

    # S3 Buckets
    print(f"S3 BUCKETS ({sm['total_buckets']} total)")
    print(f"{'Bucket Name':<25} {'Region':<11} {'Created':<13} {'Objects':<10} {'Size (MB)'}")
    for b in data['resources']['s3_buckets']:
        cd = b['creation_date'][:10] if b['creation_date'] else 'N/A'
        size_mb = b['size_bytes'] / (1024 * 1024)
        print(f"{b['bucket_name']:<25} {b['region']:<11} {cd:<13} {b['object_count']:<10} ~{size_mb:.1f}")
    print()

    # Security Groups
    print(f"SECURITY GROUPS ({sm['security_groups']} total)")
    print(f"{'Group ID':<16} {'Name':<14} {'VPC ID':<15} {'Inbound Rules'}")
    for sg in data['resources']['security_groups']:
        name = (sg['group_name'][:11] + '...') if len(sg['group_name']) > 14 else sg['group_name']
        print(f"{sg['group_id']:<16} {name:<14} {sg['vpc_id']:<15} {len(sg['inbound_rules'])}")

def main():
    parser = argparse.ArgumentParser(description="AWS Resource Inspector")
    parser.add_argument("--region", help="AWS region to inspect")
    parser.add_argument("--output", help="Output file path (default: stdout)")
    parser.add_argument("--format", choices=['json', 'table'], default='json', help="Output format")
    args = parser.parse_args()

    session = boto3.Session()
    region = args.region or session.region_name or 'us-west-2'

    # Authenticate
    account_id, user_arn = verify_auth_and_region(session, region)

    # Collect Resources
    iam_users = collect_iam_users(session)
    ec2_instances = collect_ec2_instances(session, region)
    s3_buckets = collect_s3_buckets(session)
    security_groups = collect_security_groups(session, region)

    # Construct final JSON payload
    data = {
        "account_info": {
            "account_id": account_id,
            "user_arn": user_arn,
            "region": region,
            "scan_timestamp": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        },
        "resources": {
            "iam_users": iam_users,
            "ec2_instances": ec2_instances,
            "s3_buckets": s3_buckets,
            "security_groups": security_groups
        },
        "summary": {
            "total_users": len(iam_users),
            "running_instances": len(ec2_instances),
            "total_buckets": len(s3_buckets),
            "security_groups": len(security_groups)
        }
    }

    json_data = json.loads(json.dumps(data, default=datetime_handler))

    if args.format == 'table':
        if args.output:
            original_stdout = sys.stdout
            with open(args.output, 'w') as f:
                sys.stdout = f
                print_table(json_data)
                sys.stdout = original_stdout
        else:
            print_table(json_data)
    else:
        json_string = json.dumps(json_data, indent=4)
        if args.output:
            with open(args.output, 'w') as f:
                f.write(json_string)
        else:
            print(json_string)

if __name__ == "__main__":
    main()
