# Contributing Guide

This guide will help you add support for new regions to the integration.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Development Setup](#development-setup)
- [Adding a New DTEK Region](#adding-a-new-dtek-region)
- [Testing](#testing)
- [Code Style](#code-style)
- [Example: Adding Uzhhorod Region](#example-adding-uzhhorod-region)

## Prerequisites

- uv installed
- Git installed
- GitHub account for creating PRs
- Understanding of Home Assistant integration development

## Development Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/ALERTua/ha-svitlo-yeah.git
   cd ha-svitlo-yeah
   ```

2. **Install dependencies using uv:**
   ```bash
   uv sync
   ```

3. **Run pre-commit setup:**
   ```bash
   uv run pre-commit install
   ```

4. **Verify tests pass:**
   ```bash
   uv run pytest
   ```

## Adding a New DTEK Region

### Overview

To add a new DTEK region, you need to modify several files following the established patterns. This typically involves:

1. Adding the region to the `DTEKJsonProvider` enum
2. Adding URL mappings in `DTEK_PROVIDER_URLS`
3. Updating translations in `en.json` and `uk.json`
4. Updating documentation in `README.md`
5. Testing your changes

### Step-by-Step Process

To add a new DTEK region, follow this process by examining **PR #16** as a reference example:

**Reference Example:** https://github.com/ALERTua/ha-svitlo-yeah/pull/16

#### Files to Modify:

1. **`custom_components/svitlo_yeah/models.py`**
   - Add your region to the `DTEKJsonProvider` enum
   - Add URL mapping in `DTEK_PROVIDER_URLS`

2. **`custom_components/svitlo_yeah/translations/en.json`**
   - Add provider translation key in `selector.provider.options`
   - Add region translation key in `selector.region.options`

3. **`custom_components/svitlo_yeah/translations/uk.json`**
   - Add Ukrainian translations for the same keys as in en.json

4. **`README.md`**
   - Add a new row to the supported regions table

#### Pattern to Follow:

Refer to PR #16 to see the exact pattern for:
- Enum naming conventions (`UPPER_SNAKE_CASE`)
- URL structure and data source links
- Translation key format (`dtekjsonprovider_{region_name}`)
- Table formatting in README

Each change should follow the existing patterns established by previous regions.

## Testing

### Run All Tests

```bash
uv run pytest
```

### Run Pre-commit Checks

```bash
uv run pre-commit run --all-files
```

### Test Your Region

**Verify in Home Assistant:**
  - Restart Home Assistant
  - Try to add your new region through the integration UI
  - Check if sensors are created and data loads correctly

## Code Style

### Python Code

- Follow PEP 8 style guidelines
- Use type hints where possible
- Use descriptive variable and function names
- Keep functions small and focused
- Add docstrings for complex functions

### JSON Files

- Use consistent indentation (2 spaces)
- Maintain alphabetical order when possible
- Keep translations meaningful and accurate

### Git Commits

Use clear, descriptive commit messages:

```
Add DTEK support for Uzhhorod region

- Added Uzhhorod region to DTEKJsonProvider enum
- Added URL mapping for Zakarpattiaoblenerho data
- Updated English and Ukrainian translations
- Updated README documentation
```

## Reference Example

For a complete working example of adding a DTEK region, see:
**https://github.com/ALERTua/ha-svitlo-yeah/pull/16**

This PR demonstrates the exact changes needed to add Uzhhorod region support and can serve as a template for adding new regions.

## Troubleshooting

### Common Issues:

1. **Tests failing**: Check if your enum values match the expected patterns
2. **Translation not showing**: Ensure keys match exactly between en.json and uk.json
3. **Integration not loading**: Verify all required files are modified consistently
4. **Data source not working**: Test the URL manually and ensure JSON format is valid

### Getting Help:

- Check existing issues on GitHub
- Review similar PRs for patterns
- Run tests and pre-commit locally before submitting
- Ask questions in GitHub discussions

## Security Considerations

- Always verify data sources are legitimate
- Don't commit sensitive information
- Test URLs before adding them
- Keep dependencies updated
