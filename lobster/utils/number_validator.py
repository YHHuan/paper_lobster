"""Number validation for drafts.

Ensures all numbers cited in a draft can be traced to the source material.
"""

import re
import logging

logger = logging.getLogger("lobster.utils.numbers")

# Match numbers that look like data (not dates, not section numbers)
NUMBER_PATTERN = re.compile(
    r'(?<!\d[/-])'           # not part of a date
    r'(\d+(?:\.\d+)?'        # integer or decimal
    r'(?:\s*%)?)'            # optional percentage
    r'(?![/-]\d)'            # not part of a date
)


def validate_numbers(draft: str, source_text: str) -> tuple[bool, list[str]]:
    """Check that numbers in the draft appear in the source.

    Args:
        draft: The draft text.
        source_text: The original source material.

    Returns:
        (all_valid, unverified): True if all numbers found in source,
        list of numbers not found.
    """
    draft_numbers = set(NUMBER_PATTERN.findall(draft))
    set(NUMBER_PATTERN.findall(source_text))

    # Filter out trivially common numbers (1, 2, 3, etc.)
    trivial = {str(i) for i in range(10)}
    draft_numbers -= trivial

    unverified = []
    for num in draft_numbers:
        num_clean = num.strip()
        if num_clean not in source_text:
            unverified.append(num_clean)

    if unverified:
        logger.warning(f"Unverified numbers in draft: {unverified}")

    return len(unverified) == 0, unverified
