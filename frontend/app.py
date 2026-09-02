import streamlit as st
import requests
import json
import subprocess
import os
import plotly.graph_objects as go

st.set_page_config(page_title="Financial RAG", layout="wide", initial_sidebar_state="expanded")

# Custom CSS for financial metrics & charts
st.markdown("""
<style>
    .metric-container {
        background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%);
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        padding: 12px 16px;
        margin-bottom: 12px;
    }
    .kpi-badge {
        display: inline-block;
        padding: 4px 10px;
        border-radius: 6px;
        font-weight: 600;
        font-size: 0.85rem;
    }
    .kpi-positive { background-color: #d1fae5; color: #065f46; }
    .kpi-neutral { background-color: #e0f2fe; color: #0369a1; }
    .kpi-negative { background-color: #fee2e2; color: #991b1b; }
</style>
""", unsafe_allow_html=True)

st.title("📊 Financial RAG Platform")

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
symbol_input = st.sidebar.text_input("Company Symbol (e.g., APOLLO, HAL, RELIANCE)")
doc_type_input = st.sidebar.selectbox("Document Type", ["both", "annual", "concall"])
year_input = st.sidebar.text_input("Year (Optional)")

st.sidebar.markdown("""
---
**Analytical Capabilities:**
- 📈 **Trend & CAGR Tracking**: Multi-year growth, CAGR badges, bar/line plots
- 📊 **Structural Analysis**: P&L waterfall bridges, shareholding patterns
- 📑 **Hybrid Intelligence**: SQL ground truth fused with earnings call transcripts
""")


def render_financial_visuals(charts, msg_idx: int = 0):
    """Render interactive financial charts & KPI cards at the end of the text response."""
    if not charts:
        return

    st.markdown("---")
    st.markdown("#### 📈 Financial Visual Insights")

    for idx, chart in enumerate(charts):
        # Render KPI cards if available
        kpis = chart.get("kpis", [])
        if kpis:
            cols = st.columns(min(len(kpis), 4))
            for i, kpi in enumerate(kpis):
                with cols[i % len(cols)]:
                    st.metric(label=kpi.get("label", ""), value=kpi.get("value", ""))

        # Render Plotly Figure
        fig_dict = chart.get("plotly_fig")
        if fig_dict:
            try:
                fig = go.Figure(fig_dict)
                chart_key = f"plotly_chart_{msg_idx}_{idx}_{chart.get('id', idx)}"
                # Use width='stretch' (new API) with fallback to use_container_width
                try:
                    st.plotly_chart(fig, width="stretch", key=chart_key)
                except TypeError:
                    st.plotly_chart(fig, use_container_width=True, key=chart_key)
            except Exception as e:
                st.error(f"Error rendering chart: {e}")
                # Fallback: show chart data as a simple table
                labels = chart.get("labels", [])
                values = chart.get("values", [])
                if labels and values:
                    import pandas as pd
                    df = pd.DataFrame({"Category": labels, "Value": values})
                    st.dataframe(df, use_container_width=True)
        else:
            # No plotly_fig — render a simple fallback from labels/values
            labels = chart.get("labels", [])
            values = chart.get("values", [])
            if labels and values and chart.get("type") == "donut":
                fig = go.Figure(data=[go.Pie(
                    labels=labels, values=values, hole=0.55,
                    textinfo="label+percent",
                )])
                fig.update_layout(
                    title=chart.get("title", ""),
                    height=350,
                    paper_bgcolor="rgba(0,0,0,0)",
                )
                chart_key = f"plotly_fallback_{msg_idx}_{idx}"
                try:
                    st.plotly_chart(fig, width="stretch", key=chart_key)
                except TypeError:
                    st.plotly_chart(fig, use_container_width=True, key=chart_key)
            elif labels and values:
                fig = go.Figure(data=[go.Bar(
                    x=labels, y=values,
                    marker_color="#3B82F6",
                    text=[f"₹{v:,.0f}" if isinstance(v, (int, float)) else str(v) for v in values],
                    textposition="outside",
                )])
                fig.update_layout(
                    title=chart.get("title", ""),
                    height=350,
                    paper_bgcolor="rgba(0,0,0,0)",
                )
                chart_key = f"plotly_fallback_{msg_idx}_{idx}"
                try:
                    st.plotly_chart(fig, width="stretch", key=chart_key)
                except TypeError:
                    st.plotly_chart(fig, use_container_width=True, key=chart_key)


tab1, tab2 = st.tabs(["💬 Query Interface", "⚙️ Admin Dashboard"])

with tab1:
    st.header("Ask Financial RAG")
    
    if "messages" not in st.session_state:
        st.session_state.messages = []
        
    for msg_idx, msg in enumerate(st.session_state.messages):
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("charts"):
                render_financial_visuals(msg["charts"], msg_idx=msg_idx)
            
    if prompt := st.chat_input("E.g., What is the profit CAGR and trend for APOLLO from FY23 to FY25?"):
        st.session_state.messages.append({"role": "user", "content": prompt, "charts": []})
        with st.chat_message("user"):
            st.markdown(prompt)
            
        with st.chat_message("assistant"):
            with st.spinner("Retrieving qualitative insights and querying SQL data..."):
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
                        charts = data.get("charts", [])
                        
                        if sources:
                            ans += "\n\n### Sources\n"
                            for i, src in enumerate(sources, 1):
                                dt = src.get("doc_type", "")
                                sym = src.get("symbol", "Unknown")
                                yr = src.get("year", "")
                                yr_str = f" FY{yr}" if yr else ""
                                if dt in ("sql_data", "shareholding"):
                                    doc_label = "Structured Database" if dt == "sql_data" else "Shareholding Data"
                                    section = src.get("section", "")
                                    ans += f"- **[SRC-{i}]** {sym}{yr_str} — {doc_label} ({section})\n"
                                else:
                                    doc = "Annual Report" if dt == "annual_report" else "Concall"
                                    page = src.get("page", "")
                                    page_str = f" (Page {page})" if page not in ("", -1, "-1") else ""
                                    ans += f"- **[SRC-{i}]** {sym} {doc}{yr_str}{page_str}\n"
                        
                        # Display Text Response FIRST
                        st.markdown(ans)

                        # Display Visual Charts AT THE END OF TEXTUAL RESPONSE
                        if charts:
                            render_financial_visuals(charts, msg_idx=len(st.session_state.messages))

                        st.session_state.messages.append({
                            "role": "assistant",
                            "content": ans,
                            "charts": charts
                        })
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
