# Project Instructions

> This file is automatically loaded into the agent's system prompt.
> It works like Claude Code's CLAUDE.md — persistent project-level memory.

## Project Context

- This is a Python project using ...
- Tests are in `tests/` and run with `pytest`
- The main entry point is `src/main.py`

## Coding Standards

- Use type hints for function signatures
- Follow PEP 8
- Write docstrings for public functions

## Important Notes

- Do not modify `config/production.yaml` without asking first
- The database migration in `migrations/003_*.sql` is still pending review
- CI runs on Python 3.11+
