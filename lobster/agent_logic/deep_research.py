"""Multi-step deep research agent.

Replaces the old single-call spawn_research with a proper research chain:
1. Read full source material
2. Generate follow-up questions
3. Search for answers (Tavily + academic)
4. Read the best results
5. Synthesize everything into a rich research brief

Triggered when interest_score >= 8.
"""

import json
import logging

from lobster.utils.identity_loader import load_identity

logger = logging.getLogger("lobster.agent.deep_research")

MAX_RESEARCH_STEPS = 5
PER_RESEARCH_MAX_TOKENS = 2048

QUESTION_PROMPT = """You're a research lobster digging into a discovery.

Title: {title}
Source text (partial):
{source_text}

Generate 3 follow-up questions that would make a post about this MORE interesting.
Focus on:
- What's the counter-argument or limitation?
- Is there a cross-domain connection?
- What context would a smart reader need to appreciate this?

Don't ask obvious questions. Ask what a skeptical expert would want to know.

Respond in JSON: {{"questions": ["q1", "q2", "q3"]}}"""

SYNTHESIS_PROMPT = """You are synthesizing research for a compelling social media post.

Original discovery:
Title: {title}
Source: {source_text}

Follow-up research gathered:
{research_notes}

Synthesize into a research brief. Be substantive, not summary-ish.

Respond in JSON:
{{
  "key_finding": "The core insight in one sentence",
  "counter_intuitive": "What most people would assume vs what the evidence shows",
  "methodology_note": "Anything notable about how they did this",
  "effect_size": "The actual magnitude (if applicable)",
  "limitations": "What the authors didn't mention or follow-up revealed",
  "cross_domain": "Connections to other fields discovered in research",
  "additional_context": "Key facts from follow-up research that enrich the story",
  "hook_suggestion": "A possible opening line for a post about this",
  "worth_posting": true,
  "confidence": "high/medium/low — how solid is the underlying evidence?"
}}"""


async def deep_research(
    llm_client,
    db,
    source_text: str,
    title: str = "",
    searcher=None,
    academic_search=None,
    jina_reader=None,
    browser=None,
    pdf_reader=None,
) -> dict:
    """Multi-step research chain for high-interest discoveries.

    Args:
        llm_client: LLMClient instance.
        db: Database instance.
        source_text: Initial source text.
        title: Discovery title.
        searcher: TavilySearch instance (optional).
        academic_search: AcademicSearch instance (optional).
        jina_reader: JinaReader instance (optional).
        browser: HeadlessBrowser instance (optional).
        pdf_reader: PDFReader instance (optional).

    Returns:
        Research findings dict with synthesis.
    """
    identity = await load_identity(db)
    research_notes = []

    # Step 1: Enrich source if it's thin
    if len(source_text) < 1000 and jina_reader:
        logger.info(f"Source text thin ({len(source_text)} chars), not enriching (no URL)")

    # Step 2: Generate follow-up questions
    try:
        q_prompt = QUESTION_PROMPT.format(
            title=title,
            source_text=source_text[:2000],
        )
        q_result = await llm_client.chat_json("spawn", identity, q_prompt)
        questions = q_result.get("questions", [])[:3]
        logger.info(f"Deep research questions for '{title[:40]}': {questions}")
    except Exception as e:
        logger.warning(f"Question generation failed: {e}")
        questions = []

    # Step 3: Search for answers to each question
    for i, question in enumerate(questions):
        if i >= MAX_RESEARCH_STEPS:
            break

        notes_for_q = {"question": question, "findings": []}

        # Tavily search
        if searcher:
            try:
                results = await searcher.search(question, max_results=3)
                for r in results[:2]:
                    notes_for_q["findings"].append({
                        "source": "web",
                        "title": r.get("title", ""),
                        "content": r.get("content", "")[:500],
                        "url": r.get("url", ""),
                    })
            except Exception as e:
                logger.warning(f"Tavily search failed for research Q{i+1}: {e}")

        # Academic search
        if academic_search:
            try:
                academic = await academic_search.search_all(question, max_results=2)
                for r in academic[:2]:
                    notes_for_q["findings"].append({
                        "source": r.get("source", "academic"),
                        "title": r.get("title", ""),
                        "content": r.get("content", "")[:500],
                        "url": r.get("url", ""),
                    })
            except Exception as e:
                logger.warning(f"Academic search failed for research Q{i+1}: {e}")

        # Deep read the most promising result
        if notes_for_q["findings"] and jina_reader:
            best = notes_for_q["findings"][0]
            url = best.get("url", "")
            if url:
                try:
                    # Use PDF reader for PDF URLs
                    if pdf_reader and pdf_reader.is_pdf_url(url):
                        full_text = await pdf_reader.extract_from_url(url, max_chars=5000)
                    elif browser and browser.available:
                        full_text = await browser.read_page(url, max_chars=5000)
                    else:
                        full_text = await jina_reader.read(url, max_chars=5000)

                    if full_text and len(full_text) > len(best["content"]):
                        best["content"] = full_text[:2000]
                        best["deep_read"] = True
                except Exception as e:
                    logger.warning(f"Deep read failed for {url[:50]}: {e}")

        if notes_for_q["findings"]:
            research_notes.append(notes_for_q)

    # Step 4: Synthesize everything
    if not research_notes:
        # Fall back to simple analysis if no research gathered
        logger.info("No research gathered, falling back to simple analysis")
        return await _simple_analysis(llm_client, db, source_text, title)

    try:
        notes_text = json.dumps(research_notes, ensure_ascii=False, indent=2)[:4000]
        synth_prompt = SYNTHESIS_PROMPT.format(
            title=title,
            source_text=source_text[:2000],
            research_notes=notes_text,
        )
        result = await llm_client.chat_json("spawn", identity, synth_prompt)
        result["research_depth"] = len(research_notes)
        result["sources_consulted"] = sum(len(n["findings"]) for n in research_notes)

        logger.info(
            f"Deep research complete for '{title[:40]}': "
            f"{result['research_depth']} questions, "
            f"{result['sources_consulted']} sources, "
            f"confidence={result.get('confidence', 'unknown')}"
        )
        return result

    except Exception as e:
        logger.error(f"Research synthesis failed: {e}")
        return await _simple_analysis(llm_client, db, source_text, title)


async def _simple_analysis(llm_client, db, source_text: str, title: str) -> dict:
    """Fallback: single-call analysis (old spawn behavior)."""
    from lobster.agent_logic.spawn import spawn_research
    return await spawn_research(llm_client, db, source_text, title)
