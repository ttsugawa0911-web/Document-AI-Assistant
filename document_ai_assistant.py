import os
os.environ["TOKENIZERS_PARALLELISM"] = "false"

import glob
import gradio as gr
import fitz
import pytesseract
from PIL import Image
import io
import cv2
import numpy as np
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.embeddings import SentenceTransformerEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_openai import ChatOpenAI
from langchain.chains import RetrievalQA
from langchain.prompts import PromptTemplate
from langchain_core.documents import Document
import chromadb
import logging
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from tqdm import tqdm

# --- 1. 設定 (Configuration) ---
# ★ DATA_FOLDERのハードコードを削除
IMAGE_SAVE_FOLDER = "extracted_images/"
CHROMA_HOST = "localhost"
CHROMA_PORT = "8000"
TEXT_COLLECTION_NAME = "document_texts_v2_additive" 
IMAGE_COLLECTION_NAME = "document_images_v2_additive"
EMBEDDING_MODEL = "intfloat/multilingual-e-large"
SLIDE_CREATE_KEYWORD = "Slide Create:"
PREVIEW_CACHE_FOLDER = "preview_cache/" 

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- 2. バックエンドロジック ---

# ... (get_chroma_client_with_retries, preprocess_image_for_ocr は変更ありません) ...
def get_chroma_client_with_retries(host, port, retries=8, delay=5):
    last_exception = None;
    for i in range(retries):
        try:
            logging.info(f"ChromaDBへの接続を試みます... (試行 {i+1}/{retries})"); client = chromadb.HttpClient(host=host, port=port); client.heartbeat(); logging.info("✅ ChromaDBへの接続に成功しました."); return client
        except Exception as e:
            logging.warning(f"ChromaDBへの接続に失敗しました: {e}"); last_exception = e
            if i < retries - 1: logging.info(f"{delay}秒待機して、再試行します..."); time.sleep(delay)
    raise ConnectionError(f"ChromaDBへの接続に失敗しました（試行回数: {retries}回）。") from last_exception

def preprocess_image_for_ocr(pil_img):
    ocv_img = np.array(pil_img); _, binary_img = cv2.threshold(ocv_img, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU); return Image.fromarray(binary_img)

# ★ 変更点: process_single_file に data_folder_path を引数として渡す
def process_single_file(file_path, image_save_path, data_folder_path):
    # ... (この関数内のロジック自体は変更ありませんが、プレビュー生成で元のファイルパスが必要になるため、data_folder_pathを渡すようにしています) ...
    text_documents, image_documents, image_count = [], [], 0; base_filename = os.path.splitext(os.path.basename(file_path))[0]
    try:
        if file_path.lower().endswith('.pptx'):
            prs = Presentation(file_path)
            # ... (PPTX処理は変更なし) ...
        elif file_path.lower().endswith('.pdf'):
            doc = fitz.open(file_path)
            # ... (PDF処理は変更なし) ...
    except Exception as e:
        logging.error(f"Failed to process file {file_path}: {e}"); return None
    return text_documents, image_documents, image_count, os.path.basename(file_path)

# ★ 変更点: update_previews と load_document_data に data_folder_path を渡す
def load_document_data(folder_path, image_save_path, existing_sources, progress=gr.Progress()):
    # ... (tqdmを使った進捗表示ロジックは変更なし) ...
    text_documents, image_documents, image_count = [], [], 0
    pptx_files = glob.glob(os.path.join(folder_path, '**', '*.pptx'), recursive=True)
    pdf_files = glob.glob(os.path.join(folder_path, '**', '*.pdf'), recursive=True)
    all_files = pptx_files + pdf_files
    new_files = [f for f in all_files if os.path.basename(f) not in existing_sources]
    if not new_files:
        gr.Info("新しいドキュメントはありませんでした。")
        return [], [], 0
    with ProcessPoolExecutor() as executor:
        futures = {executor.submit(process_single_file, f, image_save_path, folder_path): f for f in new_files}
        for future in tqdm(as_completed(futures), total=len(new_files), desc="新規ファイルを処理中"):
            result = future.result()
            if result:
                t_docs, i_docs, i_count, fname = result
                text_documents.extend(t_docs)
                image_documents.extend(i_docs)
                image_count += i_count
    return text_documents, image_documents, image_count


# ★ 変更点: 関数の引数に folder_path を追加
def sync_database(folder_path, chunk_size, chunk_overlap, progress=gr.Progress(track_tqdm=True)):
    if not folder_path or not folder_path.strip():
        msg = "エラー: 処理対象のフォルダパスが指定されていません。"
        gr.Error(msg); return msg
    if not os.path.exists(folder_path) or not os.path.isdir(folder_path):
         msg = f"エラー: 指定されたフォルダが存在しません: {folder_path}\n(コンテナ内のパスを指定してください)"
         gr.Error(msg); return msg
    
    # ... (DB接続ロジックは変更なし、DATA_FOLDERの代わりにfolder_pathを使用) ...
    if not os.path.exists(IMAGE_SAVE_FOLDER): os.makedirs(IMAGE_SAVE_FOLDER)
    if not os.path.exists(PREVIEW_CACHE_FOLDER): os.makedirs(PREVIEW_CACHE_FOLDER)
    try:
        client = get_chroma_client_with_retries(CHROMA_HOST, CHROMA_PORT); embeddings = SentenceTransformerEmbeddings(model_name=EMBEDDING_MODEL, encode_kwargs={'batch_size': 32}); text_db = Chroma(client=client, collection_name=TEXT_COLLECTION_NAME, embedding_function=embeddings); image_db = Chroma(client=client, collection_name=IMAGE_COLLECTION_NAME, embedding_function=embeddings); existing_docs = text_db.get(include=["metadatas"]); existing_sources = set(meta['source'] for meta in existing_docs['metadatas'] if 'source' in meta); logging.info(f"データベースに存在する処理済みファイル: {len(existing_sources)}個")
    except Exception as e: msg = f"ChromaDBへの接続または既存データの取得中にエラー: {e}"; logging.error(msg); return msg
    
    text_docs, image_docs, img_count = load_document_data(folder_path, IMAGE_SAVE_FOLDER, existing_sources, progress)

    # ... (以降のチャンク分割、DB追加ロジックは変更なし) ...
    if not text_docs and not image_docs: return f"✅ 同期完了。新しいドキュメントはありませんでした。"
    progress(0, desc="テキストを分割し、DBに追加中...")
    if text_docs:
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=int(chunk_size), chunk_overlap=int(chunk_overlap)); text_chunks = text_splitter.split_documents(text_docs); text_db.add_documents(documents=text_chunks)
    progress(0.8, desc="画像の文脈情報をDBに追加中...")
    if image_docs: 
        image_db.add_documents(documents=image_docs)
    total_docs_count = len(existing_sources) + len({doc.metadata['source'] for doc in text_docs}); return f"✅ 同期完了。{len({doc.metadata['source'] for doc in text_docs})}個の新規ドキュメントを追加処理しました。(DB内合計: {total_docs_count}個)"


# ... (initialize_systems, add_user_message は変更なし) ...
def initialize_systems():
    try:
        client = get_chroma_client_with_retries(CHROMA_HOST, CHROMA_PORT); embeddings = SentenceTransformerEmbeddings(model_name=EMBEDDING_MODEL, encode_kwargs={'batch_size': 32}); text_db = Chroma(collection_name=TEXT_COLLECTION_NAME, embedding_function=embeddings, client=client); llm = ChatOpenAI(openai_api_base="http://localhost:1234/v1", openai_api_key="not-needed", streaming=True); expert_template = "以下の参考情報とあなた自身の知識を柔軟に組み合わせて、質問に答えてください。\n参考情報:{context}\n質問:{question}\n回答:"; EXPERT_PROMPT = PromptTemplate(template=expert_template, input_variables=["context", "question"]); strict_template = "以下の参考情報のみを使って、質問に答えてください。参考情報に答えがない場合は「分かりません」と答えてください。\n参考情報:{context}\n質問:{question}\n回答:"; STRICT_PROMPT = PromptTemplate(template=strict_template, input_variables=["context", "question"]); qa_chain_expert = RetrievalQA.from_chain_type(llm=llm, chain_type='stuff', retriever=text_db.as_retriever(search_kwargs={'k': 5}), return_source_documents=True, chain_type_kwargs={"prompt": EXPERT_PROMPT}); qa_chain_strict = RetrievalQA.from_chain_type(llm=llm, chain_type='stuff', retriever=text_db.as_retriever(search_kwargs={'k': 5}), return_source_documents=True, chain_type_kwargs={"prompt": STRICT_PROMPT}); image_db = Chroma(collection_name=IMAGE_COLLECTION_NAME, embedding_function=embeddings, client=client); image_retriever = image_db.as_retriever(search_kwargs={'k': 3}); systems = {"qa_chains": {"エキスパートアシスタント": qa_chain_expert, "厳格ライブラリアン": qa_chain_strict}, "image_retriever": image_retriever, "llm": llm}; return systems, "✅ システム準備完了。ChromaDBに接続済みです。"
    except Exception as e:
        msg = f"システム初期化エラー: {e}。ChromaDBまたはLM Studioは起動していますか？"; gr.Warning(msg); logging.error(msg); return None, msg

def add_user_message(user_message, history):
    history = history + [[user_message, None]]; return "", history, gr.update(visible=False), gr.update(value=[])

# ★ 変更点: bot_response と update_previews に data_folder_path を渡す
def bot_response(history, systems_state, answering_mode, data_folder_path):
    # ... (処理自体は変更なし) ...
    if not systems_state:
        history[-1][1] = "エラー: システムが準備できていません。"; yield history, None; return
    user_message = history[-1][0]; history[-1][1] = ""; source_documents = []
    try:
        if answering_mode == "ブレインストーミング":
            llm = systems_state["llm"]
            for chunk in llm.stream(user_message):
                history[-1][1] += chunk.content; yield history, None 
        else:
            qa_chain = systems_state["qa_chains"][answering_mode]; final_answer = ""
            for chunk in qa_chain.stream({'query': user_message}):
                if "result" in chunk: final_answer += chunk["result"]; history[-1][1] = final_answer; yield history, None
                if "source_documents" in chunk: source_documents = chunk["source_documents"]
    except Exception as e:
        history[-1][1] = f"エラーが発生しました: {e}"; yield history, None
    yield history, source_documents

def update_previews(source_documents, data_folder_path):
    # ... (プレビュー生成時に data_folder_path を使うように変更) ...
    if not source_documents: return gr.update(visible=False), gr.update(value=[])
    previews = [];
    if os.path.exists(PREVIEW_CACHE_FOLDER):
        for f in glob.glob(os.path.join(PREVIEW_CACHE_FOLDER, "*")): os.remove(f)
    seen_sources = set()
    for doc in source_documents:
        source_file = doc.metadata['source']; identifier = ""; caption = ""; is_pdf = False
        if 'page_number' in doc.metadata:
            page_num = doc.metadata['page_number']; identifier = f"{source_file}_p{page_num}"; caption = f"{source_file} (p.{page_num})"; is_pdf = True
        elif 'slide_number' in doc.metadata:
            slide_num = doc.metadata['slide_number']; identifier = f"{source_file}_s{slide_num}"; caption = f"{source_file} (Slide {slide_num})"
        if identifier in seen_sources or not identifier: continue
        seen_sources.add(identifier)
        if is_pdf:
            try:
                pdf_path = os.path.join(data_folder_path, source_file) # ★ DATA_FOLDERの代わりに引数を使用
                if os.path.exists(pdf_path):
                    pdf_doc = fitz.open(pdf_path); page = pdf_doc.load_page(doc.metadata['page_number'] - 1); pix = page.get_pixmap(dpi=96); preview_img_path = os.path.join(PREVIEW_CACHE_FOLDER, f"{identifier}.png"); pix.save(preview_img_path); pdf_doc.close(); previews.append((preview_img_path, caption))
            except Exception as e: logging.error(f"PDFプレビュー生成エラー: {e}")
        else:
             previews.append((None, f"【テキストプレビュー】\n{caption}\n----------\n{doc.page_content[:500]}..."))
    return gr.update(visible=True), gr.update(value=previews)


# ★ 変更点: UIにフォルダパス入力欄を追加し、イベントハンドラを修正
with gr.Blocks(theme=gr.themes.Soft(), title="Document AI Assistant") as demo:
    systems_state = gr.State()
    source_docs_state = gr.State()

    gr.Markdown("# 🤖 Document AI アシスタント")
    with gr.Tabs():
        with gr.TabItem("チャット"):
            with gr.Row():
                with gr.Column(scale=4):
                    chatbot = gr.Chatbot(label="チャット", height=550, bubble_full_width=False, show_copy_button=True)
                    msg = gr.Textbox(label="メッセージ", placeholder="質問を入力してください...", show_label=False)
                with gr.Column(scale=1):
                    answering_mode = gr.Radio(["エキスパートアシスタント", "厳格ライブラリアン", "ブレインストーミング"], label="AI回答モード", value="エキスパートアシスタント")
                    gr.Markdown("**エキスパート:** DB知識+AI知識\n**厳格:** DB知識のみ\n**ブレイン:** AI知識のみ")
            with gr.Accordion("参照元プレビュー", open=True, visible=False) as preview_accordion:
                source_gallery = gr.Gallery(label="参照したドキュメントのページ", show_label=False, elem_id="gallery", columns=4, height="auto")

        with gr.TabItem("データベース管理"):
            with gr.Column():
                gr.Markdown("### ⚙️ データベース設定")
                
                # ★ フォルダパス入力用のTextboxを追加
                folder_path_input = gr.Textbox(
                    label="処理対象フォルダのパス",
                    placeholder="/host-docs/MedicalPapers など、コンテナ内のパスを入力",
                    info="docker-compose.ymlで設定したボリューム内のフォルダパスを指定します。"
                )

                with gr.Accordion("チャンク設定（上級者向け）", open=False):
                    chunk_size_input = gr.Number(label="Chunk Size", value=1000, step=50)
                    chunk_overlap_input = gr.Number(label="Chunk Overlap", value=150, step=10)
                
                sync_db_btn = gr.Button("Sync Database", variant="primary")
                status_output = gr.Textbox(label="システムステータス", interactive=False, lines=5)

    # イベントハンドラを修正
    msg.submit(
        add_user_message, 
        [msg, chatbot], 
        [msg, chatbot, preview_accordion, source_gallery]
    ).then(
        bot_response, 
        [chatbot, systems_state, answering_mode, folder_path_input], # folder_path_inputを追加
        [chatbot, source_docs_state]
    ).then(
        update_previews,
        [source_docs_state, folder_path_input], # folder_path_inputを追加
        [preview_accordion, source_gallery]
    )
    
    sync_db_btn.click(
        fn=sync_database, 
        inputs=[folder_path_input, chunk_size_input, chunk_overlap_input], # folder_path_inputを追加
        outputs=status_output
    ).then(fn=initialize_systems, outputs=[systems_state, status_output])
    
    demo.load(fn=initialize_systems, outputs=[systems_state, status_output])

if __name__ == "__main__":
    if not os.path.exists(PREVIEW_CACHE_FOLDER):
        os.makedirs(PREVIEW_CACHE_FOLDER)
    demo.queue()
    demo.launch()