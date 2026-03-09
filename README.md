# Janus

A Python library.

## Installation

Install from the repository (development mode):

```bash
pip install -e .
```

Once published to PyPI:

```bash
pip install janus
```

## Usage

```python
import janus

print(janus.__version__)
```

## Development

### Setup

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

### Running tests

```bash
pytest
```

## License

This project is licensed under the GNU General Public License v3.0 – see the [LICENSE](LICENSE) file for details.