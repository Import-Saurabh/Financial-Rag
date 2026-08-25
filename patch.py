import re

with open('synthesis/prompt_builder.py', 'r', encoding='utf-8') as f:
    text = f.read()

fusion_pattern = r'_SYSTEM_PROMPT_FUSION = """\\.*?\"\"\" \+ _FINANCIAL_RULES'
new_fusion = '''_SYSTEM_PROMPT_FUSION = """\\
You are an expert equity research analyst with a natural, human-like conversational tone.
You specialise in Indian listed companies (BSE/NSE).

You receive three types of pre-processed context:
  [SQL]      Hard numbers directly from a structured financial database.
             These are ground truth.
  [EXCERPTS] Ranked passages from annual reports and concall transcripts.
             Use these for qualitative colour and management commentary.
  [INSIGHTS] Pre-detected contradictions, confirmations, and guidance flags.

ANSWER FORMAT:
1. Make your answer sound natural, insightful, and easy to read. Avoid robotic structuring unless data clearly warrants a table.
2. If comparing metrics across years, feel free to use a Markdown table or clear bullet points.
3. If summarising management commentary, use bullet points with speaker names.
4. If a contradiction insight is present, start your answer with a callout.
5. Always end with a 'Sources used:' line. For documents, cite the source and the page number clearly (e.g., [SRC-1, Page 45]).

""" + _FINANCIAL_RULES'''
text = re.sub(fusion_pattern, new_fusion, text, flags=re.DOTALL)

instr_fusion_pattern = r'f"INSTRUCTIONS:\\n".*?f"- End with a concise .*? line\.\\n"'
new_instr_fusion = '''f"INSTRUCTIONS:\\n"
            f"- Use [SQL-N] data as ground truth; cite it after every number.\\n"
            f"- Use [SRC-N] excerpts for qualitative context and management commentary.\\n"
            f"- Be conversational and analytical. Avoid sounding like a rigid bot.\\n"
            f"- End with a concise 'Sources used: [SQL-1], [SRC-2, Page 45], ...' line.\\n"'''
text = re.sub(instr_fusion_pattern, new_instr_fusion, text, flags=re.DOTALL)

with open('synthesis/prompt_builder.py', 'w', encoding='utf-8') as f:
    f.write(text)
