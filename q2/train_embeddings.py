import json
import re
import torch
import sys
import argparse
import time
import os
import datetime
import torch
import torch.nn as nn
import torch.optim as optim

from collections import Counter
from torch.utils.data import Dataset, DataLoader

def build_vocabulary(papers, max_vocab_size=5000):
  word_counts = Counter()

  for paper in papers:
    abstract = paper.get("abstract", "")
    abstract = abstract.lower()

    words = re.findall(r'[a-z]+', abstract)

    for word in words:
      if len(word) >= 2:
        word_counts[word] += 1

  vocab_to_idx = {"<UNK>": 0}

  top_words = word_counts.most_common(max_vocab_size - 1)

  for idx, (word, count) in enumerate(top_words, start = 1):
    vocab_to_idx[word] = idx

  return vocab_to_idx, word_counts


class ArxivDataset(Dataset):
  def __init__(self, papers, vocab_to_idx, max_seq_length = 200):
    self.papers = papers
    self.vocab_to_idx = vocab_to_idx
    self.vocab_size = len(vocab_to_idx)
    self.max_seq_length = max_seq_length

  def __len__(self):
    return len(self.papers)

  def __getitem__(self, idx):
    abstract = self.papers[idx].get("abstract", "").lower()
    words = re.findall(r'[a-z]+', abstract)

    valid_words = [w for w in words if len(w) >= 2]
    truncated_words = valid_words[:self.max_seq_length]

    indices = [self.vocab_to_idx.get(w, 0) for w in truncated_words]

    bow_vector = torch.zeros(self.vocab_size, dtype=torch.float32)

    for word_idx in indices:
      bow_vector[word_idx] = 1.0

    return bow_vector, bow_vector           # an autoencoder's target is its own input, so i return it twice: (input data, target data)


class TextAutoencoder(nn.Module):
  def __init__(self, vocab_size, hidden_dim = 256, embedding_dim = 64):
    super().__init__()

    self.encoder = nn.Sequential(
      nn.Linear(vocab_size, hidden_dim),
      nn.ReLU(),
      nn.Linear(hidden_dim, embedding_dim)
    )

    self.decoder = nn.Sequential(
      nn.Linear(embedding_dim, hidden_dim),
      nn.ReLU(),
      nn.Linear(hidden_dim, vocab_size),
      nn.Sigmoid()
    )

  def forward(self, x):
    embedding = self.encoder(x)
    reconstruction = self.decoder(embedding)

    return reconstruction, embedding


def count_parameters(model):
  return sum(p.numel() for p in model.parameters() if p.requires_grad)


def train_model(model, dataloader, epochs):
  criterion = nn.BCELoss()                                # BCE (Binary Cross Entropy)
  optimizer = optim.Adam(model.parameters(), lr = 0.001)

  print("\nTraining autoencoder...")
  start_time = time.time()

  for epoch in range(epochs):
    total_loss = 0.0
    model.train()

    for batch_idx, (input_data, target_data) in enumerate(dataloader):
      optimizer.zero_grad()

      reconstruction, _ = model(input_data)
      loss = criterion(reconstruction, target_data)

      loss.backward()
      optimizer.step()

      total_loss += loss.item()

    avg_loss = total_loss / len(dataloader)
    print(f"Epoch {epoch + 1}/{epochs}, Loss: {avg_loss:.4f}")

  training_time = time.time() - start_time
  print(f"Training complete in {training_time:.1f} seconds")

  return avg_loss, start_time, time.time()


def main():
  parser = argparse.ArgumentParser(description = "Train text autoencoder")
  parser.add_argument("input_file", help = "Path to input JSON file")
  parser.add_argument("output_dir", help = "Directory to save outputs")
  parser.add_argument("--epochs", type = int, default = 50, help = "Number of training epochs")
  parser.add_argument("--batch_size", type = int, default = 32, help = "Batch size for training")
  args = parser.parse_args()

  # load data
  print(f"Loading abstracts from {args.input_file}...")
  with open(args.input_file, 'r') as f:
    papers = json.load(f)

  print(f"Found {len(papers)} abstracts")

  # build vocabulary
  vocab_to_idx, counts = build_vocabulary(papers, max_vocab_size = 5000)
  vocab_size = len(vocab_to_idx)
  print(f"Vocabulary size: {vocab_size} words")

  # setup dataset and dataloader
  dataset = ArxivDataset(papers, vocab_to_idx)
  dataloader = DataLoader(dataset, batch_size = args.batch_size, shuffle = True)

  # initialize model
  model = TextAutoencoder(vocab_size = vocab_size, hidden_dim = 128, embedding_dim = 64)
  total_params = count_parameters(model)
  print(f"Model architecture: {vocab_size} -> 256 -> 64 -> 256 -> {vocab_size}")
  print(f"Total parameters: {total_params:,}")

  if total_params > 2000000:
    print("Error: Parameter count exceeds the 2,000,000 limit!", file=sys.stderr)
    sys.exit(1)

  # start training
  final_loss, start_t, end_t = train_model(model, dataloader, args.epochs)

  print(f"\nSaving outputs to {args.output_dir}...")
  os.makedirs(args.output_dir, exist_ok=True)

  # file 1, save the pytorch model
  model_path = os.path.join(args.output_dir, 'model.pth')
  torch.save({
    'model_state_dict': model.state_dict(),
    'vocab_to_idx': vocab_to_idx,
    'model_config': {
      'vocab_size': vocab_size,
      'hidden_dim': 256,
      'embedding_dim': 64
    }
  }, model_path)

  # file 2, generate and save the embeddings
  model.eval()
  criterion = nn.BCELoss()
  embeddings_list = []

  with torch.no_grad():
    for i in range(len(dataset)):
      bow_tensor, _ = dataset[i]
      bow_tensor = bow_tensor.unsqueeze(0)

      reconstruction, embedding = model(bow_tensor)
      loss = criterion(reconstruction, bow_tensor)

      embedding_floats = embedding.squeeze().tolist()

      embeddings_list.append({
        "arxiv_id": dataset.papers[i].get("arxiv_id"),
        "embedding": embedding_floats,
        "reconstruction_loss": loss.item()
      })

  with open(os.path.join(args.output_dir, 'embeddings.json'), 'w') as f:
    json.dump(embeddings_list, f, indent = 2)


  # file 3, savevocabulary
  idx_to_vocab = {v: k for k, v in vocab_to_idx.items()}
  vocab_data = {
    "vocab_to_idx": vocab_to_idx,
    "idx_to_vocab": idx_to_vocab,
    "vocab_size": vocab_size,
    "total_words": sum(counts.values())
  }

  with open(os.path.join(args.output_dir, 'vocabulary.json'), 'w') as f:
    json.dump(vocab_data, f, indent=2)

  # file 4, save training log
  start_iso = datetime.datetime.fromtimestamp(start_t, datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
  end_iso = datetime.datetime.fromtimestamp(end_t, datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

  log_data = {
    "start_time": start_iso,
    "end_time": end_iso,
    "epochs": args.epochs,
    "final_loss": final_loss,
    "total_parameters": total_params,
    "papers_processed": len(papers),
    "embedding_dimension": 64
  }

  with open(os.path.join(args.output_dir, 'training_log.json'), 'w') as f:
    json.dump(log_data, f, indent=2)

  print("All outputs generated successfully!")

if __name__ == '__main__':
  main()
