---
id: extractor/niw_extraction_user_prompt
version: 1
format: python
variables: ["exhibit_id", "applicant_name", "blocks_text"]
---
Analyze this document (Exhibit {exhibit_id}) and extract structured information for an NIW petition under Matter of Dhanasar.

The applicant's name is: {applicant_name}

## Step 1: Identify Document Context and Applicant Names
First, determine: What is the PRIMARY PURPOSE of this document?
- Recommendation letter FOR {applicant_name}? (recommender praises applicant)
- Media coverage / news article ABOUT {applicant_name}?
- Official certification/degree document FOR {applicant_name}?
- Resume or CV of {applicant_name}?
- Research publication by {applicant_name}?
- Third-party background information?

IMPORTANT - Check for NAME ALIASES:
- The applicant "{applicant_name}" may appear under DIFFERENT NAMES:
  * English name vs Chinese name (or other language variations)
  * Abbreviated name, nickname, or title (Dr., Prof., etc.)
  * Same surname with similar context = likely the applicant
- If document is about someone with SAME SURNAME as "{applicant_name}" and the document is exhibit evidence for this applicant, treat that person AS the applicant.

This context determines how to classify is_applicant_achievement.

## Document Text Blocks
Each block has format: [block_id] text content

{blocks_text}

## Instructions

Extract the following in a single JSON response:

1. **document_summary**: Identify document type and primary subject
2. **snippets**: Evidence text with SUBJECT attribution
3. **entities**: All named entities with identity and relationship to applicant
4. **relations**: Relationships between entities

For each SNIPPET, you MUST determine:
- subject: Whose achievement/credential is this? (exact name or "{applicant_name}")
- subject_role: "applicant", "recommender", "evaluator", "colleague", "mentor", "peer", "organization", or "other"
- recommender_name: If this is from a recommendation/evaluation, who is the recommender?
- is_applicant_achievement:
  * TRUE if: subject is applicant, OR document is ABOUT applicant and confirms their achievement
  * TRUE ALSO if: evidence SUPPORTS applicant's case (credibility proof, impact proof)
  * FALSE only if: someone else's OWN background completely unrelated to applicant's case
- evidence_type: Choose MOST SPECIFIC type from Dhanasar prong categories (see system prompt)
- evidence_purpose: WHY does this evidence matter?
  * "direct_proof" - Directly proves applicant's qualification or endeavor merit
  * "selectivity_proof" - Proves selectivity/prestige of credential
  * "credibility_proof" - Proves source credibility
  * "impact_proof" - Proves quantitative impact or national significance

CRITICAL EXAMPLES for NIW:

1. PRONG 1 - "Applicant's research addresses the national need for renewable energy solutions":
   → evidence_type="national_importance", evidence_purpose="direct_proof"

2. PRONG 1 - "The proposed endeavor focuses on developing AI-driven diagnostic tools for early cancer detection":
   → evidence_type="endeavor_description", evidence_purpose="direct_proof"

3. PRONG 2 - "Applicant received PhD in Computer Science from MIT":
   → evidence_type="education", evidence_purpose="direct_proof"

4. PRONG 2 - "Applicant's publications have been cited over 500 times":
   → evidence_type="citation_metrics", evidence_purpose="impact_proof"

5. PRONG 2 - "Dr. Smith, a leading expert, states the applicant's work is groundbreaking":
   → evidence_type="recommendation", evidence_purpose="credibility_proof"

6. PRONG 3 - "The applicant's work benefits the broader US healthcare system, not just a single employer":
   → evidence_type="beyond_employer", evidence_purpose="direct_proof"

7. PRONG 3 - "Requiring a labor certification would delay critical research in pandemic preparedness":
   → evidence_type="urgency", evidence_purpose="direct_proof"

CRITICAL: Extract BOTH direct evidence AND supporting evidence!