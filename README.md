# auto-align

A policy/standards alignment engine built around OpenAI embeddings and tooling for mapping between different security frameworks (e.g., NIST, UAE, NCA).

## Getting Started

1. Install Python dependencies:

   ```bash
   python -m pip install -r backend/requirements.txt
   ```

2. Set your OpenAI API key (required for embedding/model calls):

   ```bash
   export OPENAI_API_KEY="your_api_key_here"     # macOS/Linux
   setx OPENAI_API_KEY "your_api_key_here"       # Windows (PowerShell)
   ```

3. Run the backend scripts or services (example):

   ```bash
   python backend/run_waves.py
   ```

4. (Optional) Start the frontend:

   ```bash
   cd frontend
   npm install
   npm run dev
   ```

## Notes

- This repo intentionally does not store API keys or other secrets. Use environment variables to provide credentials.
- If you need to configure local tooling (e.g., Claude), keep those settings out of version control (see `.gitignore`).
