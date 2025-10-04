# 🤖 Document AI Assistant

A powerful, locally-run AI assistant that allows you to chat with your documents. This application uses a Retrieval-Augmented Generation (RAG) pipeline to provide answers based on the content of your PDF and PowerPoint files. It runs entirely on your local machine, ensuring your data remains private.



## ✨ Features

-   **Multi-Format Support**: Ingests and processes both `.pdf` and `.pptx` (PowerPoint) files.
-   **Private & Local**: Runs with a local LLM (via LM Studio, Ollama, etc.) and a local vector database (ChromaDB), so your data never leaves your machine.
-   **RAG Pipeline**: Uses LangChain to create a robust RAG system for accurate, context-aware answers.
-   **Flexible Answering Modes**:
    -   **Expert Assistant**: Combines knowledge from your documents with the LLM's general knowledge.
    -   **Strict Librarian**: Answers using *only* the information found in your documents.
    -   **Brainstorming**: Functions as a standard LLM chatbot, ignoring the document database.
-   **Source Previews**: Displays image previews of the exact document pages or slides used to generate an answer.
-   **Incremental Updates**: The database sync is additive, meaning it only processes new files, saving time on subsequent runs.
-   **Web Interface**: Built with Gradio for an easy-to-use and interactive experience.

---

## 🛠️ Tech Stack

-   **Backend**: Python
-   **Web UI**: Gradio
-   **LLM Orchestration**: LangChain
-   **Vector Database**: ChromaDB
-   **Embedding Model**: Sentence-Transformers (`intfloat/multilingual-e-large`)
-   **PDF Processing**: PyMuPDF (`fitz`)
-   **PowerPoint Processing**: `python-pptx`
-   **OCR for Images**: Tesseract (`pytesseract`)
-   **LLM Backend**: Designed to work with any OpenAI-compatible API, such as **LM Studio** or **Ollama**.

---

## 🚀 Getting Started

### Prerequisites

1.  **Python**: Version 3.9 or higher.
2.  **Docker & Docker Compose**: To run the ChromaDB vector database.
3.  **Local LLM Server**:
    -   **LM Studio**: Download from [lmstudio.ai](https://lmstudio.ai/).
    -   **Ollama**: Download from [ollama.ai](https://ollama.ai/).
4.  **Tesseract OCR**: Required for extracting text from images within documents.
    -   **Windows**: Download and install from the [Tesseract installer page](https://github.com/UB-Mannheim/tesseract/wiki).
    -   **macOS**: `brew install tesseract`
    -   **Linux (Debian/Ubuntu)**: `sudo apt-get install tesseract-ocr`

### 1. Clone the Repository

```bash
git clone [https://github.com/your-username/document-ai-assistant.git](https://github.com/your-username/document-ai-assistant.git)
cd document-ai-assistant
```

### 2. Set up the Environment

It's recommended to use a Python virtual environment.

```bash
# Create and activate a virtual environment
python -m venv venv
source venv/bin/activate  # On Windows, use `venv\Scripts\activate`

# Install the required Python packages
pip install -r requirements.txt
```

*You will need to create a `requirements.txt` file with the following content:*

```txt
gradio
langchain
langchain-openai
langchain-community
sentence-transformers
chromadb-client
pypdf
python-pptx
pillow
opencv-python
pytesseract
fitz
PyMuPDF
tqdm
```

### 3. Configure Docker for ChromaDB

Create a `docker-compose.yml` file in the root of your project directory. This file will define the ChromaDB service and mount your local documents folder into the application's container environment.

```yaml
version: '3.8'

services:
  chromadb:
    image: chromadb/chroma
    container_name: chromadb
    ports:
      - "8000:8000"
    volumes:
      - chroma_data:/chroma/chroma

  # This app service is optional but recommended for isolating dependencies.
  # If you run the Python script directly on your host, you still need the 'chromadb' service above.
  app:
    build: . # You'll need a Dockerfile for this
    container_name: doc-ai-app
    ports:
      - "7860:7860" # Gradio port
    volumes:
      # Mount your local documents folder to a path inside the container
      - ./path/to/your/docs:/app/documents
    depends_on:
      - chromadb
    environment:
      - CHROMA_HOST=chromadb # Use service name for host

volumes:
  chroma_data:
```
*Note: The provided `app.py` script is configured to connect to `localhost:8000`. This works if you run the Python script directly on your host machine while the ChromaDB container is running. If you containerize the app, you'll need to adjust `CHROMA_HOST` in the script or use environment variables.*

### 4. Start the Services

1.  **Start your Local LLM**: Open LM Studio or run Ollama and load a model. Ensure the server is running (usually at `http://localhost:1234/v1`).
2.  **Start ChromaDB**: Open a terminal in your project directory and run:
    ```bash
    docker-compose up -d
    ```

### 5. Run the Application

With your LLM and ChromaDB running, start the Gradio application:

```bash
python app.py
```

Open your web browser and navigate to `http://127.0.0.1:7860`.

---

## 📖 How to Use

1.  **Place Documents**: Add your `.pdf` and `.pptx` files into the local folder you mapped in the `docker-compose.yml` file (e.g., `./path/to/your/docs`).

2.  **Sync Database**:
    -   Navigate to the **Database Management** tab in the web UI.
    -   In the **Target Folder Path** box, enter the *path inside the container* where your documents are located (e.g., `/app/documents`).
    -   Click the **Sync Database** button. The application will process all new files and add them to the vector store. You can monitor the progress in the terminal.

3.  **Start Chatting**:
    -   Go to the **Chat** tab.
    -   Select your preferred **AI Answering Mode**.
    -   Type your question in the message box and press Enter.
    -   The AI will respond, and if applicable, the **Source Previews** section will show the relevant pages from your documents.

---

## 📄 License

This project is licensed under the MIT License. See the `LICENSE` file for details.
