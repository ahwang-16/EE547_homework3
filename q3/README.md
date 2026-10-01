o## Problem 3: AWS Resource Inspector

### Error Handling & Permission Failures
This script implements isolated fault tolerance for API operations. Each resource collection function (IAM, EC2, S3, Security Groups) operates within its own `try/except` boundary block designed to catch `botocore.exceptions.ClientError`. 

When an `AccessDenied` exception is raised (e.g., if the IAM role lacks `s3:ListAllMyBuckets`), the script catches the specific error code, bypasses the collection for that localized resource, prints a non-blocking `[WARNING]` or `[ERROR]` to `sys.stderr`, and continues executing the remainder of the script. This ensures the output payload is still generated containing all permitted resources rather than crashing completely. Additionally, network timeouts are handled natively via a custom boto3 `Config` object initialized with `retries={'max_attempts': 1}`, automatically retrying network drops once before failing gracefully.

### Assumptions about AWS Account Configuration
1. **Credentials:** It is assumed that valid AWS credentials are provided either via the standard `~/.aws/credentials` file (`aws configure`) or via system environment variables. The script relies on boto3's default credential provider chain to resolve them. 
2. **S3 Region Fallbacks:** The script assumes that S3 buckets returning `None` for their `LocationConstraint` are hosted in the default `us-east-1` region, per standard AWS API behavior.
3. **AMI Privacy:** It is assumed that some EC2 AMIs may be private or deleted post-launch. If `ec2:DescribeImages` throws an error due to a missing AMI, the script defaults the AMI Name to "Unknown" rather than crashing the EC2 collection loop.
