# Hundred Keks 🤪

This is a fork of 8baller's 100x Python Client [hundred-x](https://github.com/8ball030/hundred_x).

I focused on updating everything to latest, which makes it more likely to break.

Differences include:
- uses my fork of [py-eip712-structs](https://github.com/wakamex/py-eip712-structs) (see [changes](https://github.com/wakamex/py-eip712-structs?tab=readme-ov-file#changes-in-12))
- use of `uv` instead of `poetry`
- test with python up to 3.12
- no longer support python 3.9
- test on ubuntu-latest
- fewer direct dependencies
- fewer lint tools (ruff replaces black, isort, flake8, and pylint)
- only pytest for testing (no tox)


## Installation
```bash
clone the repo
uv pip install -e .
```