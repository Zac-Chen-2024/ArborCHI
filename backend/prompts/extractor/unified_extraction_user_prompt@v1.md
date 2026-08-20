---
id: extractor/unified_extraction_user_prompt
version: 1
format: python
variables: ["exhibit_id", "applicant_name", "blocks_text"]
---
Analyze this document (Exhibit {exhibit_id}) and extract structured information.

The applicant's name is: {applicant_name}

## Step 1: Identify Document Context and Applicant Names
First, determine: What is the PRIMARY PURPOSE of this document?
- Recommendation letter FOR {applicant_name}? (recommender praises applicant)
- Media coverage / news article ABOUT {applicant_name}?
- Official certification/membership document FOR {applicant_name}?
- Resume or CV of {applicant_name}?
- Third-party background information?

IMPORTANT - Check for NAME ALIASES:
- The applicant "{applicant_name}" may appear under DIFFERENT NAMES:
  * English name vs Chinese name (or other language variations)
  * Abbreviated name, nickname, or title (Dr., Prof., Coach, etc.)
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
  * TRUE ALSO if: evidence SUPPORTS applicant's case (selectivity proof, credibility proof, impact proof)
  * FALSE only if: someone else's OWN background completely unrelated to applicant's case
- evidence_type: Choose MOST SPECIFIC type (see system prompt for full list)
- evidence_purpose: WHY does this evidence matter?
  * "direct_proof" - Directly proves applicant's achievement
  * "selectivity_proof" - Proves selectivity/prestige (other members' achievements, strict criteria)
  * "credibility_proof" - Proves source credibility (media circulation, organization reputation)
  * "impact_proof" - Proves quantitative impact (page views, user counts, revenue)

CRITICAL EXAMPLES:

1. DIRECT PROOF - Recommendation letter says "The applicant revolutionized X":
   → subject="{applicant_name}", is_applicant_achievement=TRUE, evidence_purpose="direct_proof"

2. NOT APPLICANT - Recommender says "I (Dr. Smith) have 20 years at Stanford":
   → subject="Dr. Smith", is_applicant_achievement=FALSE (recommender's own background)

3. DIRECT PROOF - News article says "{applicant_name} founded [company/organization]":
   → subject="{applicant_name}", is_applicant_achievement=TRUE, evidence_type="media_coverage", evidence_purpose="direct_proof"

4. SELECTIVITY PROOF - Membership document says "Other members include Olympic gold medalist Ping Zhang":
   → subject="Ping Zhang", is_applicant_achievement=TRUE, evidence_type="peer_achievement", evidence_purpose="selectivity_proof"
   → This PROVES the association is selective, which supports applicant's membership!

5. SELECTIVITY PROOF - "Membership requires 10 years experience and outstanding achievements":
   → subject="the association", is_applicant_achievement=TRUE, evidence_type="membership_criteria", evidence_purpose="selectivity_proof"

6. CREDIBILITY PROOF - "[Publication name] has circulation of X and won [journalism award]":
   → subject="[publication]", is_applicant_achievement=TRUE, evidence_type="source_credibility", evidence_purpose="credibility_proof"
   → This PROVES the publication is "major media", which supports applicant's media coverage!

7. IMPACT PROOF - "The courses received 100,000 page views and trained 200,000 coaches":
   → subject="{applicant_name}", is_applicant_achievement=TRUE, evidence_type="quantitative_impact", evidence_purpose="impact_proof"

8. CREDIBILITY PROOF - "Company has AAA credit rating":
   → subject="the company", is_applicant_achievement=TRUE, evidence_type="source_credibility", evidence_purpose="credibility_proof"
   → This PROVES the organization is "distinguished", which supports applicant's leading role!

9. IMPACT PROOF - "5,000,000 people participated in the event":
   → subject="the event", is_applicant_achievement=TRUE, evidence_type="quantitative_impact", evidence_purpose="impact_proof"
   → This PROVES the scale of applicant's leadership impact!

10. IMPACT PROOF - "300 athletes from 10 countries competed":
    → subject="the competition", is_applicant_achievement=TRUE, evidence_type="quantitative_impact", evidence_purpose="impact_proof"
    → This PROVES international reach and significance!

11. CREDIBILITY PROOF - "weekly circulation of 200,000 copies":
    → subject="the publication", is_applicant_achievement=TRUE, evidence_type="source_credibility", evidence_purpose="credibility_proof"

12. SELECTIVITY PROOF - "membership requires 10 years experience and review by board of directors":
    → subject="the association", is_applicant_achievement=TRUE, evidence_type="membership_criteria", evidence_purpose="selectivity_proof"

13. SALARY (criterion ix) - "The applicant's annual salary was ¥961,710" or "annual income RMB 961,710":
    → subject="{applicant_name}", is_applicant_achievement=TRUE, evidence_type="salary", evidence_purpose="direct_proof"
    → NEVER classify salary as quantitative_impact!

14. SALARY BENCHMARK (criterion ix) - "The national average salary for fitness professionals is ¥323,032":
    → subject="industry", is_applicant_achievement=TRUE, evidence_type="salary_benchmark", evidence_purpose="impact_proof"
    → Comparison data PROVES the applicant's salary is significantly higher!

15. COMPENSATION (criterion ix) - "iQIYI paid ¥150,000 for the applicant's consulting services":
    → subject="{applicant_name}", is_applicant_achievement=TRUE, evidence_type="compensation", evidence_purpose="direct_proof"

16. JUDGING (criterion iv) - "The applicant served as a reviewer for the Journal of Sports Science":
    → subject="{applicant_name}", is_applicant_achievement=TRUE, evidence_type="judging", evidence_purpose="direct_proof"

17. JUDGING (criterion iv) - "Invited to evaluate grant proposals for the National Science Foundation":
    → subject="{applicant_name}", is_applicant_achievement=TRUE, evidence_type="judging", evidence_purpose="direct_proof"

18. PUBLICATION (criterion vi) - "The applicant authored 'Advanced Training Methods' published in Sports Medicine Journal":
    → subject="{applicant_name}", is_applicant_achievement=TRUE, evidence_type="publication", evidence_purpose="direct_proof"
    → This is criterion (vi) because the applicant WROTE it. NOT media_coverage!

19. EXHIBITION (criterion vii) - "The applicant's paintings were displayed at the National Art Museum":
    → subject="{applicant_name}", is_applicant_achievement=TRUE, evidence_type="exhibition", evidence_purpose="direct_proof"

20. COMMERCIAL SUCCESS (criterion x) - "The film directed by the applicant grossed $50 million at the box office":
    → subject="{applicant_name}", is_applicant_achievement=TRUE, evidence_type="commercial_success", evidence_purpose="direct_proof"

CRITICAL EXTRACTION PATTERNS — what to look for in EVERY document:
- Numbers + units: "40,000 copies", "100,000 views", "5M participants", "14 stores", "10 countries"
- Currency amounts: ¥, $, RMB, USD, 元 — determine if salary/compensation (→ criterion ix) or other metric (→ criterion v)
- Salary keywords: "salary", "income", "compensation", "fee", "wage", "pay", "remuneration"
- Benchmark keywords: "average", "median", "national", "industry", "comparison", "higher than", "X times"
- Ratings: "AAA", "credit rating"
- Awards to organizations: "won ... Award", "received ... prize"
- Peer credentials: "members include", "other recipients", "Olympic", "champion", "gold medal"
- Media rankings: "leading", "top", "largest", "most", "first", "circulation"
- Review/judging: "reviewed", "referee", "judge", "evaluated", "committee", "editorial board"
- Authorship: "published in", "authored", "co-authored", "textbook", "monograph", "cited"
- Exhibition: "exhibited", "displayed", "gallery", "museum", "showcase", "festival screening"
- Commercial: "box office", "grossed", "sold", "revenue", "bestseller", "platinum"

CRITICAL: Extract BOTH direct evidence AND supporting evidence!
- Direct evidence: What the applicant did
- Supporting evidence: Why it matters (selectivity, credibility, impact)
Do NOT skip supporting evidence - it is ESSENTIAL for EB-1A petitions!