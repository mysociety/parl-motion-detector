
# parl-motion-detector

This repository is to make a motion and agreement extractor that enhances our existing transcripts.

The end goal is to:

- Extract 'Agreements' - when decisions are made without a vote.
- For Agreements and Divisions - connect to the motion or motions that are being voted on in chain.

Unsolved problems:

- We're getting titles from Parliament for divisions - we'll have to create them (automatically?) for agreements.

## Quick Start

### Development Environment

The project uses a development container. To set up:

```bash
# Initialize the development environment
script/setup

# Install dependencies and configure
poetry install

# Run tests to verify setup
script/test
```

### Data Processing

```bash
# Process current year data for House of Commons
project process-current-year --chamber house-of-commons

# Process current year data for Scottish Parliament
project process-current-year --chamber scottish-parliament

# Process a specific historical year
project process-year 2023 --chamber house-of-commons

# Process all historical data
project process-historical --chamber house-of-commons

# Just rebuild the package files without reprocessing
project recreate-package

# Remove current year parquets (useful for daily updates)
project remove-current-year-parquets
```

### Testing and Quality Assurance

```bash
# Run full test suite (includes pytest, ruff linting, and type checking)
script/test

# Fix linting issues automatically
script/lint

# Refresh test snapshots for motion detection
project refresh-snapshot

# Build and validate datasets
dataset build --all
dataset version auto --auto-ban major --all
```

## Maintenance Commands

### Automated Workflows

The project includes automated GitHub Actions workflows:

- **Daily Processing**: Runs at 8 AM UTC daily (`build_and_publish.yml`)
  - Processes current year data for both chambers
  - Builds and publishes datasets
  - Updates GitHub Pages documentation
  - Notifies Slack on success/failure
  - Triggers refresh webhook for external services

- **Testing**: Runs on pull requests (`test.yml`)
  - Executes full test suite
  - Builds datasets for validation
  - Runs version checks

### Manual Data Corrections

The project uses two manual correction files to handle edge cases:

#### 1. Manual Motion Linking (`data/raw/manual_motion_linking.json`)

This file manually links motions to divisions/agreements that the automatic algorithm cannot correctly identify. Each entry contains:

```json
{
  "motion_gid": "uk.org.publicwhip/debate/2020-02-04e.212.5.1",
  "decision_gid": "uk.org.publicwhip/debate/2020-02-04e.262.0"
}
```

Or for more complex cases with inline motion definitions:

```json
{
  "decision_gid": "uk.org.publicwhip/debate/2024-10-09c.415.0",
  "motion": {
    "chamber": "house-of-commons",
    "date": "2024-10-09",
    "gid": "uk.org.publicwhip/debate/2024-10-09c.332.0.2",
    "speech_id": "uk.org.publicwhip/debate/2024-10-09c.332.0",
    "motion_lines": ["[Reasoned amendment - opposing a second reading]"],
    "motion_title": "Renters' Rights Bill: Reasoned Amendment to Second Reading"
  }
}
```

**When to add entries:**
- When divisions/agreements are not automatically linked to their correct motions
- When the motion text needs to be manually specified
- For complex procedural votes that don't follow standard patterns

#### 2. Pre-2019 Dates (`data/raw/pre_2019_dates.json`)

This file contains a list of dates (in YYYY-MM-DD format) before 2019 that should be processed to pick up agreements

This is to catch specific dates with significant votes, without needing to deal with all edge cases for that pierod. 

```json
[
  "2017-11-28",
  "2005-10-26",
  "2011-11-07"
]
```

### Data Validation

- `data/tests/mapper/`: Contains expected motion-to-decision mappings for specific dates
- `data/tests/motions/`: Contains motion detection test cases

Test files are named by date (e.g., `2024-02-21.json`) and contain:

```json
{
  "division_motions": {
    "decision_gid": "motion_gid"
  },
  "agreement_motions": {
    "decision_gid": "motion_gid"
  }
}
```

### Troubleshooting Common Issues

**Motion not linking correctly:**
1. Check if the date exists in test data (`data/tests/mapper/`)
2. Verify the motion and decision GIDs are correct
3. Add manual linking entry to `manual_motion_linking.json`
4. Run tests to validate: `script/test`

**Historical data not processing:**
1. Ensure the date is in `pre_2019_dates.json` (if before 2019)
2. Check transcript availability in the source data
3. Use `project process-year YYYY` to process specific years

**"Too many motions" error during current year processing:**

This error occurs when the automatic motion detection algorithm finds multiple possible motions for a single decision and cannot determine which one is correct.

1. **Re-run the failing command** to see the detailed output:
   ```bash
   project process-current-year --chamber house-of-commons
   ```

2. **Examine the output before the error** - the system will print:
   - The decision GID that's causing the issue
   - All candidate motion GIDs that could be linked
   
4. **Add manual linking** to `data/raw/manual_motion_linking.json`:
   ```json
   {
     "decision_gid": "uk.org.publicwhip/debate/YYYY-MM-DDx.XXX.X",
     "motion_gid": "uk.org.publicwhip/debate/YYYY-MM-DDx.XXX.X.X"
   }
   ```

5. **Re-run processing** to verify the fix:
   ```bash
   project process-current-year --chamber house-of-commons
   ```

**Data package build failures:**
1. Run `dataset build --all` to see specific errors
2. Check for data validation issues in the logs
3. Verify all required manual correction files are present