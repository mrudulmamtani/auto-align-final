FROM python:3.12-slim
WORKDIR /app

# Build tools needed by tokenizers / numpy C extensions
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Install CPU-only torch first (avoids pulling the ~2 GB GPU wheel)
RUN pip install --no-cache-dir \
    torch --extra-index-url https://download.pytorch.org/whl/cpu

RUN pip install --no-cache-dir -r requirements.txt || \
    pip install --no-cache-dir $(grep -v docx2pdf requirements.txt | grep -v '^#' | grep -v '^$' | tr '\n' ' ')

# Diagram rendering dependencies
RUN pip install --no-cache-dir matplotlib requests

# Pre-download NER + embedding models at build time
RUN python -m spacy download en_core_web_sm
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

# Copy application code
COPY app/ ./app/

# Copy AutoAlign data files and artifacts
COPY NIST3.json uae.json nca_oscal_catalog.json ./
COPY oai_nist_vecs.pkl oai_uae_vecs.pkl oai_nca_vecs.pkl ./
COPY policy_output/ ./policy_output/
COPY forensic_maps/ ./forensic_maps/
COPY org_templates/ ./org_templates/
RUN mkdir -p converted_output

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8100"]
