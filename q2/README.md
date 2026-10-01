# Problem 2: Text Embedding Training with Autoencoders

## Architecture & Parameter Count
The autoencoder utilizes a symmetric feed-forward neural network architecture:
`Input (5000) → Hidden (128) → Bottleneck (64) → Hidden (128) → Output (5000)`.

## Design Rationale
**Vocabulary Size (5,000):** A vocabulary limit of 5,000 was chosen as the optimal balance between semantic coverage and parameter constraints. Attempting to encompass the typical 10,000 or more words found in technical abstracts would cause the initial and final linear layers to easily exceed the 2,000,000 parameter budget. Capping the vocabulary captures the vast majority of high-frequency, domain-specific terminology while safely satisfying the grading limits.

**Embedding Dimension (64):** The embedding dimension serves as the information bottleneck. A dimension of 64 was selected to ensure it is sufficiently tight compared to the hidden layers. This prevents the network from merely memorizing the sparse input vectors, forcing it instead to compress the text into mathematically dense, semantically meaningful relationships.

## Bag-of-Words (BoW) Construction
The conversion of a raw text abstract into a PyTorch-compatible Bag-of-Words tensor follows a strict preprocessing pipeline:

1. **Text Cleaning:** The raw text abstract is first converted entirely to lowercase. A regular expression (`r'[a-z]+'`) is applied to extract only maximal sequences of letters, cleanly stripping all punctuation, digits, and hyphenation.
2. **Filtering & Truncation:** Any isolated letters or strings shorter than two characters are dropped. To prevent abnormally long abstracts from heavily skewing the data distribution, the remaining sequence of words is truncated to a maximum length of 200 words.
3. **Index Mapping:** Using the pre-computed vocabulary frequency mapping, each remaining word is converted into its respective integer index. Any word falling outside the top 5,000 is mapped to index `0` (the `<UNK>` token).
4. **Tensor Population:** An empty PyTorch tensor of length 5,000 is initialized and filled with zeros. The script iterates through the mapped word indices, updating the corresponding position in the tensor to `1.0` for every index present in the abstract. The resulting tensor serves as both the input and the target for the autoencoder's binary cross-entropy loss.

## Execution
To build and run the training pipeline using the provided Docker configuration:

```bash
docker build -t arxiv-embeddings:latest .
docker run --rm \
    -v "$(pwd)/papers.json":/data/input/papers.json:ro \
    -v "$(pwd)/output":/data/output \
    arxiv-embeddings:latest \
    /data/input/papers.json /data/output --epochs 50 --batch_size 32
