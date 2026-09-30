# RAG Evaluation Results (V2)

### Q1: What was Apollo Micro Systems' revenue for FY2025-26?
**Answer:**
⚠️ **Contradiction:** The revenue figure reported in the structured data (₹904.0 cr) differs from an alternative figure mentioned elsewhere (₹379.8 lakh), exceeding the system’s divergence threshold.

**Revenue for FY 2025‑26 (FY 2026):** ₹904.0 crore [SQL-1]

- Management highlighted a strategic acquisition of IDL Explosives for **₹107 crore** in November 2025, marking the group’s entry into the explosives and energetics value chain. This deal is likely a key driver behind the revenue uplift observed in FY 2026 [ SRC-1 ].

**Sources used:** [SQL-1], [SRC-1]

*Model: Groq - GPT OSS 120B | Latency: 11.77s | Citations: 2*

---

### Q2: What was the company's net profit for FY2025-26?
**Answer:**
⚠️ **Contradiction note:** The structured financial table reports a net profit of **₹107.0 crore** for FY 2025‑26, while the management commentary in the annual report (Note 43) cites a net profit of **₹11,292.04 lakhs** for the year.

- **Reported net profit (ground‑truth):** ₹107.0 crore for the fiscal year ending 31 Mar 2026【SQL-1】.  
- **Management‑statement figure:** Net profit of ₹11,292.04 lakhs (basic EPS ₹3.35) mentioned in the earnings‑per‑share note【SRC-2】.  

The structured data is taken as the definitive figure for FY 2025‑26.

**Sources used:** [SQL-1], [SRC-2, Note 43].

*Model: Groq - GPT OSS 120B | Latency: 6.02s | Citations: 2*

---

### Q3: What was the EBITDA for FY2025-26?
**Answer:**
⚠️ **Contradiction:** The structured database reports FY 2025‑26 EBITDA as ₹218 crore, while the FY 2025‑26 annual report cites a standalone EBITDA of ₹231.22 crore.

- **SQL‑based figure (ground truth):** EBITDA (Operating Profit + Depreciation) = **₹218 crore** for FY 2025‑26【SQL-3】.  
- **Document‑based figure:** The company states that “EBITDA grew 73.50 % to **₹231.22 crore** with a standalone EBITDA margin of 30.23 %” for FY 2025‑26【SRC-2】.  

Management highlights in the same report point to strong margin expansion and operating leverage driving this growth【SRC-2】.

**Takeaway:** Depending on whether you consider the consolidated (SQL) or standalone (report) numbers, EBITDA for FY 2025‑26 is either ₹218 crore or ₹231.22 crore.

**Sources used:** [SQL-3], [SRC-2, Page ‑1]

*Model: Groq - GPT OSS 120B | Latency: 5.22s | Citations: 2*

---

### Q4: What was the total revenue from operations?
**Answer:**
⚠ **Contradiction alert** – The structured database reports Reliance’s total revenue for FY 2026 as **₹1,055,780.0 crore** [SQL-1], while the annual‑report excerpt for FY 2025 cites revenue of **₹90,432.38 lakhs** (≈₹9,043 crore) [SRC-1]. The two figures differ dramatically, suggesting a possible reporting or unit mismatch.

**What the data say**

- **Reliance (FY 2026)** – Total revenue from operations (as recorded in the financial database) = **₹1,055,780.0 crore** [SQL-1].

**Management commentary (qualitative colour)**  

- In the FY 2025 annual report, Reliance disclosed “total revenue from contracts with customers of **₹90,432.38 lakhs**” (product revenue **₹89,189.21 lakhs**, service income **₹1,243.17 lakhs**) [SRC-1].  
- The same report notes that the acquisition of IDL Explosives added **₹13,764.39 lakhs** of revenue for the period 15 Nov 2025 – 31 Mar 2026.  

Given the stark difference between the structured figure and the narrative disclosure, treat the ₹1,055,780.0 crore number as the authoritative total revenue for FY 2026, but be aware that the narrative figures (in lakhs) point to a much lower scale for FY 2025.

**Bottom line** – According to the ground‑truth database, Reliance’s total revenue from operations in FY 2026 was **₹1,055,780.0 crore**.

**Sources used:** [SQL-1], [SRC-1].

*Model: Groq - GPT OSS 120B | Latency: 5.67s | Citations: 2*

---

### Q5: What was the company's total assets at the end of FY2025-26?
**Answer:**
Reliance Industries’ total assets at the close of FY 2025‑26 (31 Mar 2026) were **₹2,177,546.0 crore**【SQL-1】.  

* The structured financial database is the definitive source for this figure; the annual‑report excerpts don’t contain any commentary on total assets for the period.  

**Sources used:** [SQL-1]

*Model: Groq - GPT OSS 120B | Latency: 7.10s | Citations: 2*

---

### Q6: What was the EPS for FY2025-26?
**Answer:**
The company reported the following earnings‑per‑share for FY 2025‑26:

- **Basic EPS:** ₹3.57 per share  
- **Diluted EPS:** ₹3.53 per share  

These figures come from the FY 2025‑26 annual report, where the profit attributable to equity shareholders was ₹12,057.89 lakhs and the weighted‑average share counts were 33,74,56,014 (basic) and 34,12,58,425 (diluted) 【SRC-3】.

*Management notes that the small gap between basic and diluted EPS reflects the dilutive effect of pending share warrants 【SRC-4】.*

**Sources used:** [SRC-3], [SRC-4]

*Model: Groq - GPT OSS 120B | Latency: 3.60s | Citations: 3*

---

### Q7: How did revenue change from FY2024-25 to FY2025-26?
**Answer:**
Revenue: Not available in current database.  

Sources used: —

*Model: Groq - GPT OSS 120B | Latency: 1.98s | Citations: 1*

---

### Q8: What was the percentage growth in revenue?
**Answer:**
Revenue: Not available in current database.  

Sources used: [SRC-1], [SRC-2], [SRC-3], [SRC-4], [SRC-5]

*Model: Groq - GPT OSS 120B | Latency: 2.97s | Citations: 5*

---

### Q9: How did net profit change year over year?
**Answer:**
**Net profit (PAT) more than doubled year‑on‑year**

- FY 25 PAT: ₹5,724.16 lakhs  
- FY 26 PAT: ₹12,057.89 lakhs  
- YoY change: +110.65 % (PAT rose from ₹5,724.16 lakhs to ₹12,057.89 lakhs)  

**What drove the jump?**  
- Revenue surged 36 % to ₹76,485.32 lakhs, lifting gross profit and EBITDA margins.  
- Higher gross profit (62 % YoY) and a modest rise in depreciation kept operating leverage strong, translating into a sharp EBIT rise (79 %).  

**Takeaway:** The company’s net profit more than doubled, reflecting robust top‑line growth and improved profitability margins.

**Sources used:** [SRC-2, p.53]

*Model: Groq - GPT OSS 120B | Latency: 3.66s | Citations: 4*

---

### Q10: What were Apollo Micro Systems' current assets and current liabilities?
**Answer:**
**Current assets (₹ Lakhs)**  

- **Standalone balance sheet (as at 31 Mar 2026):** ₹ 1,50,404.28 [ SRC-2, p.1 ]  
- **Consolidated balance sheet (as at 31 Mar 2026):** ₹ 1,66,511.88 [ SRC-3, p.1 ]

*Both figures are presented in lakhs, as reported in the FY‑2026 annual report.*

**Current liabilities:** Not available in the provided documents.  

---

*Sources used: [SRC-2, p.1], [SRC-3, p.1]*

*Model: Groq - GPT OSS 120B | Latency: 3.65s | Citations: 3*

---

### Q11: What was the company's operating cash flow?
**Answer:**
Reliance’s operating cash flow for the fiscal year ended 31 Mar 2026 was **₹192,113.0 crore**【SQL-1】. The annual report excerpts don’t contain any management commentary on this figure, so the number stands as the reported cash generated from operations for FY 2026【SRC-1】.  

**Sources used:** [SQL-1], [SRC-1]

*Model: Groq - GPT OSS 120B | Latency: 5.45s | Citations: 2*

---

### Q12: Did the company generate positive free cash flow?
**Answer:**
The company **did not generate positive free cash flow** in FY 2026.

- Reported free cash flow (FCF) is **₹‑357.0 crore** [SQL-5].  
- If we recompute it from the cash‑flow components:  
  - Cash from operations (CFO) = **₹‑130.0 crore** [SQL-1]  
  - Capital expenditures (Capex) = **₹228.0 crore** [SQL-4]  
  - FCF = CFO − Capex = (‑130.0 − 228.0) = **₹‑358.0 crore**, which aligns with the reported ‑357 crore figure.

Thus, the firm’s cash‑generating activities were insufficient to cover its investment outlays, resulting in a negative free cash flow for the year.

**Sources used:** [SQL-5], [SQL-1], [SQL-4]

*Model: Groq - GPT OSS 120B | Latency: 4.54s | Citations: 3*

---

### Q13: What was Apollo Micro Systems' gross profit margin?
**Answer:**
Gross profit margin: Not available in current database.  

Sources used: [SRC-1], [SRC-2], [SRC-3], [SRC-4], [SRC-5]

*Model: Groq - GPT OSS 120B | Latency: 3.75s | Citations: 5*

---

### Q14: What was its operating profit margin?
**Answer:**
**Operating profit margin (FY 2026): 27.68%**  

- The FY 2026 profit‑and‑loss summary shows EBIT of ₹21,173.15 lakhs on revenue of ₹76,485.32 lakhs, giving an EBIT (operating profit) margin of **27.68%** [**SRC‑1, p.53**].  
- Management highlighted that the higher margin stemmed from a strong revenue jump (≈ 36% YoY) and a modest rise in depreciation, which kept operating leverage in favour.  

*Sources used: [SRC-1, p.53]*

*Model: Groq - GPT OSS 120B | Latency: 5.99s | Citations: 5*

---

### Q15: What was its ROE?
**Answer:**
ROE: Not available in current database.  

Sources used:

*Model: Groq - GPT OSS 120B | Latency: 1.53s | Citations: 0*

---

### Q16: What are Apollo Micro Systems' main business segments?
**Answer:**
Apollo Micro Systems Limited operates across a handful of tightly‑linked defence‑technology segments:

- **Defence electronics & electromechanical subsystems** – The company supplies roughly **63 % of the electronics and electromechanical work for DRDO missile programmes** and is described as the “industry participant with the highest participation in DRDO’s indigenous missile programmes”【SRC‑3】. This covers radar, guidance, control and other missile‑system components.  

- **Naval mine and underwater weapons** – Apollo develops and offers **MIGM (Multi‑Influence Ground Mine “Vighna”)**, moored/deep‑sea mines and torpedo homing & signal‑processing systems (EHWT, ALWT, Varunastra) in partnership with DRDO and Bharat Dynamics【SRC‑1】.  

- **Explosives & energetics** – Through the **100 % equity acquisition of IDL Explosives Ltd for ₹107 crore** (completed Nov 2025), Apollo has entered the explosives value chain, integrating the business into its operations and reporting【SRC‑2】.  

- **Integrated defence platforms** – Apollo positions itself as a **development‑cum‑production partner (DcPP)** for a range of DRDO projects, from missile subsystems to naval mines, leveraging a four‑decade‑long relationship with the agency【SRC‑4】.  

These segments together form the core of Apollo’s defence‑oriented portfolio, with a strong emphasis on DRDO‑backed programmes and a recent push into explosives manufacturing.

**Sources used:** [SRC-1, p.-1], [SRC-2, p.-1], [SRC-3, p.-1], [SRC-4, p.-1]

*Model: Groq - GPT OSS 120B | Latency: 5.32s | Citations: 3*

---

### Q17: What does management identify as the company's major growth opportunities?
**Answer:**
Management points to several levers that could drive the next wave of growth for Apollo Micro Systems (AMS):

- **Rising defence budgets** – The company notes that global and Indian military spending is on an upward trajectory, creating a larger addressable market for its weapon‑electronics platforms [SRC‑2].  
- **Indigenisation push** – Government policies that favour domestic sourcing (e.g., “Make in India”, iDEX, DAP) are expected to open new contracts and reduce reliance on imports, a clear growth catalyst for AMS’s in‑house capabilities [SRC‑2].  
- **Strategic partnerships & acquisitions** – Recent M&A activity, such as the acquisition of IDL Explosives Ltd., expands the product portfolio into explosives manufacturing and broadens the customer base [SRC‑2].  
- **Space‑sector expansion** – Management highlights the fast‑growing Indian and global space markets, where AMS can leverage its electronics expertise for commercial and defence‑related satellite programmes [SRC‑3].  
- **Technology & cyber‑security edge** – Continued investment in stage‑gated development, rigorous testing and cybersecurity safeguards is positioned as a differentiator that can win higher‑value, technology‑intensive contracts [SRC‑1].

These themes together form the backbone of AMS’s growth narrative, though the evidence comes mainly from a single annual‑report excerpt, so the confidence level is moderate.

**Sources used:** [SRC‑1, p.-1]; [SRC‑2, pages 23‑34]; [SRC‑3, p.152]

*Model: Groq - GPT OSS 120B | Latency: 5.26s | Citations: 4*

---

### Q18: What major risks does management identify?
**Answer:**
**Management’s key risk themes**

- **Market risk** – exposure to interest‑rate and foreign‑currency movements. A 1 % rise in rates would cut profit before tax by about ₹532 lakhs (FY25: ₹331 lakhs)【SRC-5】.  
- **Credit risk** – ageing of trade receivables shows sizable balances past due (₹35,296 lakhs within term, ₹6,967 lakhs 91‑180 days, ₹5,831 lakhs >180 days)【SRC-5】.  
- **Liquidity risk** – the maturity profile of borrowings and trade payables spans on‑demand to 1‑5 years, highlighting refinancing and cash‑flow pressures【SRC-5】.  
- **Raw‑material & supply‑chain cost volatility** – fluctuations in electronic components, metals and energy inputs are managed via long‑term vendor contracts and pass‑through pricing【SRC-1】.  
- **Working‑capital intensity** – defence contracts generate higher working‑capital needs, mitigated through milestone‑linked billing and disciplined receivables management【SRC-1】.  
- **Regulatory & licensing compliance** – expanded obligations (e.g., explosives manufacturing under the Explosives Act, 1884) are addressed via dedicated compliance functions and statutory audits【SRC-1】.  
- **Cybersecurity** – protection of classified programme data and operational technology through access controls, network segregation and periodic security assessments【SRC-1】.  

These risks are overseen by senior management and reviewed by the Board, with policies regularly updated to reflect the evolving operating environment【SRC-2】【SRC-3】【SRC-4】.

**Sources used:** [SRC-1], [SRC-2], [SRC-3], [SRC-4], [SRC-5]

*Model: Groq - GPT OSS 120B | Latency: 5.71s | Citations: 5*

---

### Q19: What role does Apollo Micro Systems play in India's defence ecosystem?
**Answer:**
Apollo Micro Systems (AMS) is positioning itself as a key integrator and supplier across several high‑tech defence programmes in India:

- **Strategic partner for DRDO projects** – AMS supplies critical subsystems for the QRSAM missile, torpedo homing and signal‑processing kits (EHWT, ALWT, Varunastra), and is the approved production agency for the MIGM naval mine. It also collaborates on Project Kusha and deep‑sea mine concepts, indicating a broad footprint in naval and missile systems [SRC-1].
- **Forward‑integration into energetics** – The 2025 acquisition of IDL Explosives Limited for ₹107 crore gave AMS a direct entry into the explosives and energetics value chain, adding high‑explosive licences (TNT, RDX, HMX) to its portfolio and enabling it to move from electronics into complete energetic systems [SRC-2, SRC-3].
- **Industry‑wide supplier role** – By delivering onboard systems for Project Kusha and acting as the sole industry supplier for certain DRDO trials, AMS is becoming a go‑to vendor for indigenous defence hardware, complementing other defence manufacturers such as Bharat Dynamics Limited [SRC-1].

Overall, Apollo Micro Systems is evolving from a niche electronics and fuze maker into a broader defence‑systems integrator, covering missile subsystems, naval mines, torpedoes, and now explosives/energetics. This multi‑segment involvement helps deepen India’s self‑reliance in critical defence technologies.

**Sources used:** [SRC-1], [SRC-2], [SRC-3]

*Model: Groq - GPT OSS 120B | Latency: 5.10s | Citations: 3*

---

### Q20: What defence products or systems does the company manufacture?
**Answer:**
Apollo Micro Systems (Apollo) is building a fairly broad defence‑product portfolio aimed at both domestic users and export markets. Key systems and product families mentioned in the latest annual‑report excerpts include:

- **Avionics systems** – the company secured its maiden export order for an avionics package, which it touts as a validation of its engineering and quality capabilities for overseas customers. [SRC-1, p.-1]  
- **Mines** – both **moored** and **deep‑sea** naval mines are under development. [SRC-1, p.-1]  
- **Aerial bombs** – nine variants of drop‑bombs have been created for release from aircraft platforms. [SRC-1, p.-1]  
- **Submarine bombs** – dedicated underwater ordnance for submarine deployment. [SRC-1, p.-1]  
- **Rockets** – a range of rocket systems is part of the export‑focused portfolio. [SRC-1, p.-1]  
- **Loitering‑munition marine craft (kamikaze boats)** – specialised surface‑craft that act as self‑destructing weapons. [SRC-1, p.-1]  
- **Vehicle‑mounted counter‑drone systems (VMCDS)** – field trials are slated for FY 2026‑27, signalling a move into anti‑UAV technology. [SRC-1, p.-1]  
- **Missiles, ATGMs, torpedoes, underwater mines, aerial bombs, rockets** – covered under the DPIIT lifetime Arms Manufacturing Licence, enabling export of these categories. [SRC-1, p.-1]  
- **Explosives & energetics** – the 100% equity acquisition of IDL Explosives Limited for **₹107 crore** brings the group into the explosives value chain. [SRC-3, p.-1]

Together, these items illustrate Apollo’s strategy of expanding from core avionics into a full‑fledged suite of weapons, munitions and counter‑drone solutions, with a clear eye on export‑ready, licence‑covered products.

**Sources used:** [SRC-1, p.-1], [SRC-3, p.-1]

*Model: Groq - GPT OSS 120B | Latency: 6.78s | Citations: 4*

---

### Q21: Who is the Chairman of Apollo Micro Systems?
**Answer:**
Chairman: Not available in current database.  

Sources used: [SRC-1]

*Model: Groq - GPT OSS 120B | Latency: 3.80s | Citations: 4*

---

### Q22: Who are the members of the Audit Committee?
**Answer:**
**Audit Committee members:** Not available in current database.  

Sources used: [SRC-2, p.69]

*Model: Groq - GPT OSS 120B | Latency: 5.26s | Citations: 4*

---

### Q23: Revenue increased during FY2025-26. Did net profit increase at the same rate? Explain the difference.
**Answer:**
⚠️ **Contradiction detected** – the structured figures for revenue and net profit differ markedly from an alternative source flagged in the insights.

**Growth rates (FY 2025 → FY 2026)**  

| Metric | FY 2025 | FY 2026 | YoY growth |
|--------|---------|---------|------------|
| Revenue (₹ cr) | 562.0 cr [SQL-2] | 904.0 cr [SQL-1] | ((904 − 562) / 562) × 100 = **+60.8 %** |
| Net profit (₹ cr) | 56.0 cr [SQL-4] | 107.0 cr [SQL-3] | ((107 − 56) / 56) × 100 = **+91.1 %** |

**What the numbers tell us**

- Revenue jumped about **61 %**, a solid top‑line expansion.  
- Net profit surged roughly **91 %**, outpacing revenue growth.  

**Possible reasons for the faster profit rise**  

- The higher profit growth suggests margin improvement—perhaps better cost control, a more favorable product mix, or operational efficiencies.  
- The excerpt provided ([SRC-1]) focuses on employee benefit assumptions and does not contain management commentary on revenue or profit drivers, so the specific reasons cannot be confirmed from the available documents.

**Bottom line:** Net profit did increase, and it grew at a markedly higher rate than revenue, indicating that the company likely improved its profitability margins during FY 2025‑26, though the exact drivers are not detailed in the supplied qualitative material.

**Sources used:** [SQL-1], [SQL-2], [SQL-3], [SQL-4], [SRC-1]

*Model: Groq - GPT OSS 120B | Latency: 6.11s | Citations: 5*

---

### Q24: What happened to receivables and inventory, and what does this imply about the company's working-capital position?
**Answer:**
**Receivables and inventory both surged, squeezing cash flow**

- **Trade receivables** jumped by **₹21,460.81 lakhs** in FY 2025‑26 [ SRC-2 ].  
- **Inventories** rose even faster, up **₹15,941.92 lakhs** over the same period [ SRC-2 ].  
- The combined effect drove **net cash used in operating activities** to **₹15,298.78 lakhs** (a cash outflow) [ SRC-2 ].

**What this says about working‑capital health**

- The sharp rise in receivables means sales are being booked faster than cash is collected, tying up funds in customers.  
- The inventory build‑up—partly linked to recent acquisitions and heavy capex—suggests stock is accumulating faster than it’s being turned over.  
- Together, these trends create a **working‑capital drag**, reflected in the sizable operating cash outflow. Management’s commentary flags this as a “working‑capital intensity” issue, hinting at potential pressure on liquidity until the backlog is cleared or collection improves.

*Given the magnitude of the increases, the company’s short‑term liquidity appears strained, and tighter credit or inventory management will likely be a focus going forward.*

**Sources used:** [SRC-2, Page 45]

*Model: Groq - GPT OSS 120B | Latency: 5.87s | Citations: 5*

---

### Q25: What was Apollo Micro Systems' revenue growth percentage from FY2024-25 to FY2025-26?
**Answer:**
**Revenue growth FY 2025 → FY 2026**

| FY | Revenue (₹ Cr) | YoY Growth |
|----|----------------|-----------|
| 2025 | 562.0 cr [SQL‑2] | – |
| 2026 | 904.0 cr [SQL‑1] | (904 − 562) / 562 × 100 = **60.9 %** |

**How the number is derived**  
Growth = (Revenue FY 2026 − Revenue FY 2025) / Revenue FY 2025 × 100  
= (904 cr − 562 cr) / 562 cr × 100 = 60.9 %  

**Management colour (qualitative context)**  
- The FY 2025‑26 annual report notes the **₹107 cr acquisition of IDL Explosives** (all‑cash) completed in Nov 2025, marking Apollo’s entry into the explosives and energetics value chain【SRC‑1】. This strategic move likely underpins a sizable portion of the revenue uplift.  
- No explicit commentary on the revenue jump is provided in the excerpts, so the growth figure is driven purely by the reported financials.

**Caveat**  
A contradiction flag highlights that an alternative source reported the FY 2026 revenue as “379.8 lakh”, a 58 % divergence from the ₹904 cr figure. We treat the structured [SQL‑1] data as ground truth but note the inconsistency.

**Sources used:** [SQL‑1], [SQL‑2], [SRC‑1]

*Model: Groq - GPT OSS 120B | Latency: 8.35s | Citations: 3*

---

### Q26: Calculate the difference between EBITDA and PAT for FY2025-26.
**Answer:**
**EBITDA – PAT (FY 2025‑26)**  
- EBITDA (Operating Profit + Depreciation) for FY 2026: **₹218.0 cr** [SQL-5]  
- Net profit (PAT) for FY 2026: **₹107.0 cr** [SQL-1]  

**Difference:**  
\(218.0 – 107.0 = 111.0\) crore ₹ → **₹111.0 cr**  

*There’s no management commentary on these figures in the supplied excerpts.*  

**Sources used:** [SQL-5], [SQL-1]

*Model: Groq - GPT OSS 120B | Latency: 13.92s | Citations: 2*

---

### Q27: What was the company's revenue? Cite the exact page/table.
**Answer:**
Revenue: Not available in current database.

Sources used: [SRC-1], [SRC-2], [SRC-3], [SRC-4], [SRC-5]

*Model: Groq - GPT OSS 120B | Latency: 3.82s | Citations: 5*

---

### Q28: According to the MD&A, what were the key growth drivers? Cite the relevant paragraph.
**Answer:**
**Key growth drivers:** Not available in the provided documents.

**Sources used:** [SRC-1], [SRC-2]

*Model: Groq - GPT OSS 120B | Latency: 4.00s | Citations: 3*

---

### Q29: What was Apollo Micro Systems' revenue in FY2027-28?
**Answer:**
Revenue (FY 2027‑28): Not available in current database.  

Sources used: None (no revenue figure provided in the supplied data).

*Model: Groq - GPT OSS 120B | Latency: 5.19s | Citations: 5*

---

### Q30: How many missiles did Apollo Micro Systems manufacture in FY2025-26?
**Answer:**
**Missiles manufactured in FY 2025‑26:** Not available in the current database.  

- The FY 2025‑26 annual report highlights Apollo’s **lifetime arms manufacturing licence** covering missiles, ATGMs, torpedoes, etc., and notes the **completion of the IDL Explosives acquisition** to expand energetics capabilities, but it does not disclose a production volume for missiles [SRC‑3].  
- Management also references ongoing projects such as **Project Kusha**, **MIGM**, and **QRSAM**, indicating a focus on development and supply rather than reporting specific missile output [SRC‑5].  

*Sources used: [SRC-3, p.-1], [SRC-5, p.-1]*

*Model: Groq - GPT OSS 120B | Latency: 3.77s | Citations: 5*

---

### Q31: Analyze Apollo Micro Systems' FY2025-26 financial performance using revenue growth, EBITDA, PAT, margins, operating cash flow, debt, and working capital. Then connect these financial results with the company's order book, defence-sector strategy, growth opportunities, and risks mentioned in the annual report. Cite the specific sections/pages supporting each conclusion.
**Answer:**
**Apollo Micro Systems – FY 2025‑26 snapshot (most recent year first)**  

| Metric (₹ Cr) | FY 2026 | FY 2025 | YoY % change |
|---------------|---------|---------|--------------|
| EBITDA (Operating profit + Depreciation) | 218.0 [SQL‑5] | 129.0 [SQL‑6] | ((218‑129)/129) × 100 = **+69.0 %** |
| Operating cash flow (CFO) | –130.0 [SQL‑1] | 10.0 [SQL‑13] | ((‑130‑10)/10) × 100 = **‑1,400 %** |
| Capex | 228.0 [SQL‑10] | 92.0 [SQL‑16] | ((228‑92)/92) × 100 = **+147.8 %** |
| Free cash flow (FCF) | –357.0 [SQL‑11] | –82.0 [SQL‑17] | ((‑357‑(‑82))/‑82) × 100 = **+335.4 %** (more negative) |
| Net cash flow | 49.0 [SQL‑12] | 40.0 [SQL‑18] | ((49‑40)/40) × 100 = **+22.5 %** |

**EBITDA CAGR (2025‑26)**  
CAGR = (EBITDA₍₂₀₂₆₎ / EBITDA₍₂₀₂₅₎)^(1/1) ‑ 1  
= (218 / 129) ‑ 1 = **+69.0 %** (same as YoY because the period is one year) [SQL‑5, SQL‑6].

### What’s missing?
- **Revenue / revenue growth:** Not available in the provided data.  
- **PAT (profit after tax) & margins:** Not available.  
- **Debt & working‑capital figures:** Not available.  

### Linking the numbers to strategy & risks  
The current data set does not contain any excerpts that discuss the order book, defence‑sector strategy, growth opportunities, or risk factors. Consequently, I cannot draw direct connections between the financial trends above and the qualitative commentary from the annual report.

---

**Sources used:** [SQL‑1], [SQL‑5], [SQL‑6], [SQL‑10], [SQL‑11], [SQL‑12], [SQL‑13], [SQL‑16], [SQL‑17], [SQL‑18]

*Model: Groq - GPT OSS 120B | Latency: 17.15s | Citations: 2*

---

