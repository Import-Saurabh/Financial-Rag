import streamlit as st
import requests
import json
import subprocess
import os

st.set_page_config(page_title="Financial RAG", layout="wide")

st.title("Financial RAG Platform")

try:
    prov_res = requests.get("http://127.0.0.1:5000/providers", timeout=2)
    prov_data = prov_res.json()
    provider_options = {p["id"]: p["label"] for p in prov_data}
    if not provider_options:
        provider_options = {"auto": "Auto-Select (Best Available)"}
except:
    provider_options = {"auto": "Auto-Select (Best Available)"}

st.sidebar.header("⚙️ Query Settings")
provider = st.sidebar.selectbox(
    "LLM Provider", 
    options=list(provider_options.keys()), 
    format_func=lambda x: provider_options.get(x, x)
)
symbol_input = st.sidebar.text_input("Company Symbol (e.g., ADANIPORTS)")
doc_type_input = st.sidebar.selectbox("Document Type", ["both", "annual", "concall"])
year_input = st.sidebar.text_input("Year (Optional)")

st.sidebar.markdown("""
**Architecture:**
1. **Retrieval**: Searches Qdrant Vector DB
2. **Reranking**: Uses local cross-encoder
3. **Generation**: Uses selected LLM
""")

tab1, tab2 = st.tabs(["💬 Query Interface", "⚙️ Admin Dashboard"])

with tab1:
    st.header("Ask Financial RAG")
    
    if "messages" not in st.session_state:
        st.session_state.messages = []
        
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            
    if prompt := st.chat_input("E.g., Compare the HAL revenue growth between FY24 and FY25..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
            
        with st.chat_message("assistant"):
            with st.spinner("Retrieving and generating..."):
                try:
                    payload = {
                        "query": prompt,
                        "doc_type": doc_type_input,
                        "symbol": symbol_input.strip() if symbol_input.strip() else None,
                        "year": int(year_input.strip()) if year_input.strip().isdigit() else None,
                        "provider": provider
                    }
                    res = requests.post("http://127.0.0.1:5000/query", json=payload, timeout=180)
                    if res.status_code == 200:
                        data = res.json()
                        ans = data.get("answer")
                        if ans is None:
                            ans = "No answer returned."
                            
                        sources = data.get("sources", [])
                        
                        if sources:
                            ans += "\n\n### Sources\n"
                            for i, src in enumerate(sources, 1):
                                doc = "Annual Report" if src.get("doc_type") == "annual_report" else "Concall"
                                ans += f"- **[SRC-{i}]** {src.get('symbol', 'Unknown')} {doc} FY{src.get('year', '0')} (Page {src.get('page', '-1')})\n"
                        
                        st.markdown(ans)
                        st.session_state.messages.append({"role": "assistant", "content": ans})
                    else:
                        st.error(f"Error {res.status_code}: {res.text}")
                except Exception as e:
                        st.error(f"Failed to connect to server: {e}")

with tab2:
    st.header("Ingestion Dashboard")
    st.write("Upload or select documents to ingest into the OpenKB knowledge graph.")
    
    col1, col2 = st.columns(2)
    with col1:
        symbol = st.text_input("Company Symbol (e.g., HAL, APOLLO)")
        doc_type = st.selectbox("Document Type", ["annual", "concall"])
        run_ingest = st.button("Run Ingestion (Batch)")
        
    if run_ingest:
        with st.spinner("Compiling pages into OpenKB PageIndex tree..."):
            try:
                env = os.environ.copy()
                env["PYTHONIOENCODING"] = "utf-8"
                # Call compilation bridge directly using deepseek model
                cmd = ["python", "compilation_bridge.py", "--symbol", symbol, "--type", doc_type, "--llm-model", "deepseek/deepseek-chat"]
                result = subprocess.run(cmd, env=env, capture_output=True, text=True)
                
                if result.returncode == 0:
                    st.success(f"Successfully ingested {symbol} {doc_type} documents!")
                    with st.expander("View Logs"):
                        st.text(result.stdout)
                else:
                    st.error(f"Ingestion failed with exit code {result.returncode}")
                    with st.expander("Error Details"):
                        st.text(result.stderr or result.stdout)
            except Exception as e:
                st.error(f"Ingestion execution failed: {e}")

