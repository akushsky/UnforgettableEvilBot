# Pre-Commit Setup

This project uses pre-commit hooks to ensure code quality and test coverage before each commit.

## What's Included

The pre-commit configuration includes:

### Code Quality Checks
- **Black**: Python code formatter
- **isort**: Import statement sorter
- **flake8**: Linter with additional plugins
- **MyPy**: Type checker
- **Bandit**: Security vulnerability scanner
- **pydocstyle**: Documentation style checker

### Test Enforcement
- **pytest**: Runs all tests before commit
- **Coverage**: Ensures test coverage is maintained

### File Checks
- Trailing whitespace removal
- End-of-file fixer
- YAML/JSON/TOML/XML validation
- Merge conflict detection
- Large file detection

## Setup

### Option 1: Using pre-commit framework (Recommended)

1. Install pre-commit:
```bash
pip install pre-commit
```

2. Install the git hooks:
```bash
pre-commit install
```

3. (Optional) Install all hooks in all environments:
```bash
pre-commit install --hook-type pre-commit --hook-type pre-push --hook-type commit-msg
```

### Option 2: Using the backup hook

If you prefer not to use the pre-commit framework:

1. Copy the backup hook:
```bash
cp .git/hooks/pre-commit.backup .git/hooks/pre-commit
```

2. Make it executable:
```bash
chmod +x .git/hooks/pre-commit
```

## Usage

### Normal Workflow

1. Make your changes
2. Stage your files: `git add .`
3. Commit: `git commit -m "Your message"`

The pre-commit hooks will automatically run and:
- Format your code
- Check for issues
- Run all tests
- Only allow commit if everything passes

### Manual Testing

You can run the hooks manually:

```bash
# Run all hooks
pre-commit run --all-files

# Run specific hook
pre-commit run pytest

# Run hooks on staged files only
pre-commit run
```

### Skipping Hooks (Emergency Only)

If you absolutely need to skip the hooks (not recommended):

```bash
git commit --no-verify -m "Emergency commit"
```

## Test Requirements

The test hook ensures:
- All 524 tests pass
- Coverage remains at 72% or higher
- No regressions are introduced

## Troubleshooting

### Common Issues

1. **Virtual environment not found**
   - Ensure you're in the project root
   - Run: `python -m venv .venv`
   - Activate: `source .venv/bin/activate`

2. **pytest not found**
   - Install: `pip install pytest pytest-cov`

3. **Pre-commit not found**
   - Install: `pip install pre-commit`

4. **Hook fails on first run**
   - Run: `pre-commit run --all-files` to install dependencies

### Updating Hooks

To update to the latest versions:

```bash
pre-commit autoupdate
```

## Configuration

The configuration is in `.pre-commit-config.yaml`. Key settings:

- **Black line length**: 88 characters
- **isort profile**: black-compatible
- **flake8 plugins**: docstrings, import-order, bugbear, comprehensions
- **MyPy**: Ignores missing imports
- **Bandit**: Excludes test files
- **pydocstyle**: Google convention, excludes tests/migrations

## Benefits

- **Prevents broken code**: Tests must pass before commit
- **Consistent formatting**: All code follows the same style
- **Security**: Automatic security vulnerability scanning
- **Quality**: Type checking and linting catch issues early
- **Documentation**: Ensures proper docstring formatting

## Team Workflow

1. All team members should install pre-commit hooks
2. Code reviews should check that hooks pass
3. CI/CD can use the same hooks for consistency
4. Regular updates to hook versions maintain security
