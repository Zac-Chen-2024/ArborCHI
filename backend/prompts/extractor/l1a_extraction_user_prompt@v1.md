---
id: extractor/l1a_extraction_user_prompt
version: 1
format: python
variables: ["exhibit_id", "applicant_name", "blocks_text"]
---
Analyze this document (Exhibit {exhibit_id}) and extract structured information for an L-1A intracompany transferee petition.

The beneficiary's name is: {applicant_name}

## Step 1: Identify Document Context
First, determine: What is the PRIMARY PURPOSE of this document?
- Corporate formation document (Certificate of Incorporation, By-laws)?
- Ownership/stock transfer record?
- Lease agreement or premises documentation?
- Business plan or financial projection?
- Tax return or audit report?
- Organizational chart?
- Company letter describing position and duties?
- Resume or degree certificate?
- Transaction documents (contracts, invoices, bills of lading)?
- Bank statements or investment records?

IMPORTANT - Check for NAME ALIASES:
- The beneficiary "{applicant_name}" may appear under DIFFERENT NAMES:
  * English name vs Chinese name (or other language variations)
  * Abbreviated name, nickname, or title (Ms., Mr., etc.)
- If document is about someone with SAME SURNAME as "{applicant_name}" and the document is exhibit evidence for this beneficiary, treat that person AS the beneficiary.

## Document Text Blocks
Each block has format: [block_id] text content

{blocks_text}

## Instructions

Extract the following in a single JSON response:

1. **document_summary**: Identify document type and primary subject
2. **snippets**: Evidence text with SUBJECT attribution
3. **entities**: All named entities with identity and relationship to beneficiary
4. **relations**: Relationships between entities

For each SNIPPET, you MUST determine:
- subject: Whose achievement/action is this? (exact name or "{applicant_name}")
- subject_role: "applicant", "organization", "colleague", or "other"
- is_applicant_achievement:
  * TRUE if: directly about the beneficiary's qualifications/duties/achievements
  * TRUE ALSO if: about the petitioner/parent company (supports the petition)
  * FALSE only if: completely unrelated background information
- evidence_type: Choose MOST SPECIFIC type from L-1A categories (see system prompt)
- evidence_purpose: WHY does this evidence matter?

CRITICAL EXAMPLES for L-1A:

1. CORPORATE STRUCTURE - "[Company] is a U.S. corporation formed and registered in the State of [State] on [date]":
   → evidence_type="incorporation", evidence_purpose="direct_proof"

2. OWNERSHIP - "[Shareholder] transferred [X]% of shares to [Foreign Parent Company]":
   → evidence_type="share_transfer", evidence_purpose="direct_proof"

3. PREMISES - "The premises, covering [X] square feet, provide office and warehouse space":
   → evidence_type="physical_premises", evidence_purpose="direct_proof"

4. INVESTMENT - "The parent company transferred USD $[amount] to the Petitioner":
   → evidence_type="investment", evidence_purpose="impact_proof"

5. EXECUTIVE DUTIES - "Perform executive leadership and strategic direction (approximately [X]% of Working Time)":
   → evidence_type="executive_duties", evidence_purpose="direct_proof"

6. SUBORDINATE - "The [Title] [Name]'s duties include: oversee [Department] operations":
   → evidence_type="subordinate_credentials", evidence_purpose="direct_proof"

7. REVENUE - "Gross revenue reached $[amount] by [date]":
   → evidence_type="revenue", evidence_purpose="impact_proof"

8. EMPLOYMENT - "The Beneficiary has served as [Title] of [Company] since [date]":
   → evidence_type="employment_history", evidence_purpose="direct_proof"

9. ACHIEVEMENT - "The Beneficiary executed a supply contract with [Partner] for [product/service]":
   → evidence_type="contract_execution", evidence_purpose="direct_proof"

10. PARENT COMPANY - "[Foreign Parent Company] achieved gross revenue of [currency] [amount]":
    → evidence_type="financial_performance", evidence_purpose="impact_proof"

CRITICAL: Extract BOTH direct evidence AND supporting evidence!