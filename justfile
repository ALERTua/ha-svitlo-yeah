# Windows local testing commands for Public Dashboard
# https://github.com/casey/just
set dotenv-load

# Set shell for non-Windows OSs:
set shell := ["powershell", "-c"]

# Set shell for Windows OSs:
set windows-shell := ["powershell.exe", "-NoLogo", "-Command"]

lint:
    uv run ruff format .
    uv run ruff check --fix

pre:
    uv run pre-commit run --all-files

pre-update:
    uv run pre-commit autoupdate

install:
    uv sync --dev

upgrade:
    uv sync --dev --upgrade

version VERSION:
    uv run script/update_version.py {{VERSION}}
    uv lock

# Show available commands
help:
    @just --list
