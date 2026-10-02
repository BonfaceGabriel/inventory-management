#!/usr/bin/env python3
"""Validate all SKILL.md files in .agents/skills/ directory.

Usage:
    python .agents/skills/validate_skills.py

Checks:
    - YAML frontmatter is valid
    - Required fields: name, description, metadata.domain
    - SKILL.md filename exists in each subdirectory
    - Directory name matches 'name' field in frontmatter
    - Content after frontmatter is non-empty
"""

import os
import re
import sys
import yaml

SKILLS_DIR = os.path.dirname(os.path.abspath(__file__))

SKILL_DIRS = [
    d for d in os.listdir(SKILLS_DIR)
    if os.path.isdir(os.path.join(SKILLS_DIR, d))
]

def parse_frontmatter(content):
    match = re.match(r'^---\s*\n(.*?)\n---\s*\n?(.*)', content, re.DOTALL)
    if not match:
        return None, content
    try:
        return yaml.safe_load(match.group(1)), match.group(2)
    except yaml.YAMLError as e:
        return None, str(e)

def validate_skill(dir_name):
    skill_path = os.path.join(SKILLS_DIR, dir_name, "SKILL.md")
    errors = []
    warnings = []

    if not os.path.exists(skill_path):
        return [f"Missing SKILL.md in {dir_name}/"], []

    with open(skill_path) as f:
        content = f.read()

    fm, rest = parse_frontmatter(content)
    if fm is None:
        errors.append(f"Invalid or missing YAML frontmatter: {rest}")
        return errors, warnings

    if "name" not in fm:
        errors.append("Missing 'name' in frontmatter")
    elif fm["name"] != dir_name:
        warnings.append(f"name '{fm['name']}' != directory name '{dir_name}'")

    if "description" not in fm:
        errors.append("Missing 'description' in frontmatter")
    elif len(fm["description"]) < 20:
        warnings.append(f"Description is very short ({len(fm['description'])} chars)")

    meta = fm.get("metadata", {})
    if not meta.get("domain"):
        warnings.append("No metadata.domain set")

    if not rest or len(rest.strip()) < 50:
        warnings.append(f"Skill body is very short ({len(rest.strip())} chars)")

    return errors, warnings

def main():
    all_errors = []
    all_warnings = []
    for d in sorted(SKILL_DIRS):
        errors, warnings = validate_skill(d)
        status = "PASS"
        if errors:
            status = "FAIL"
        elif warnings:
            status = "WARN"
        print(f"[{status:4s}] {d}/")
        for e in errors:
            print(f"        ERROR: {e}")
            all_errors.append((d, e))
        for w in warnings:
            print(f"        WARN:  {w}")
            all_warnings.append((d, w))

    print(f"\n{'='*50}")
    print(f"Skills: {len(SKILL_DIRS)}  Errors: {len(all_errors)}  Warnings: {len(all_warnings)}")
    if all_errors:
        print("FAILED - fix errors above")
        sys.exit(1)
    print("ALL PASSED")
    sys.exit(0)

if __name__ == "__main__":
    main()
