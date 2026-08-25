import streamlit as st
import requests
import json
import subprocess
import os

st.set_page_config(page_title="Financial RAG", layout="wide")

st.title("Financial RAG Platform")

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
                        "doc_type": "both",
                        "auto": True
                    }
                    res = requests.post("http://127.0.0.1:5000/query", json=payload, timeout=60)
                    if res.status_code == 200:
                        data = res.json()
                        ans = data.get("answer", "No answer returned.")
                        
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
                # Call compilation bridge directly
                cmd = ["python", "compilation_bridge.py", "--symbol", symbol, "--type", doc_type]
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

