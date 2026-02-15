# PDF Generation Setup

## Overview

The medical reports are automatically converted from Markdown (`.md`) to PDF (`.pdf`) using `pandoc` with the `xelatex` engine for proper Unicode support (emojis, checkmarks, etc.).

## Requirements

### On Your Laptop (macOS)

Already configured! You have:
- ✓ `pandoc` (via Homebrew)
- ✓ `xelatex` (via MacTeX)

### On the Robot (Unitree Booster - Ubuntu/Linux)

The robot needs these packages for PDF generation:

```bash
# SSH into the robot
ssh booster@192.168.10.102

# Install pandoc
sudo apt update
sudo apt install -y pandoc

# Install TeX Live (includes xelatex)
sudo apt install -y texlive-xetex texlive-fonts-recommended
```

**Note:** TeX Live is ~200MB. If space is limited on the robot, you can skip this. The robot will generate `.md` files, and they'll be converted to PDF on your laptop when displayed in the webapp.

## How It Works

1. `final_demo.py` calls `TriagePipeline.build_report()`
2. `report_builder.py` generates the `.md` file
3. `md_to_pdf.py` automatically converts it to `.pdf` using:
   - **Primary**: `markdown` + `weasyprint` (requires system libs)
   - **Fallback 1**: `pypandoc` (Python wrapper)
   - **Fallback 2**: `pandoc` subprocess with `xelatex` (← currently used)
4. Both `.md` and `.pdf` paths are posted to the command center
5. Webapp displays the report and makes PDF clickable

## Testing

Test PDF generation manually:

```bash
cd /Users/jeremyky/Documents/treehacks2026/himpublic-py
source .venv/bin/activate

# Convert all MD files in reports/
python -m himpublic.tools.convert_reports_to_pdf --dir reports

# Or convert a single file
python -c "
from himpublic.utils.md_to_pdf import md_to_pdf
pdf_path = md_to_pdf('reports/triage_20260215_005741.md')
print(f'PDF: {pdf_path}')
"
```

## Viewing PDFs

In the webapp at `http://localhost:5176/`:
- The **Medical Report** box (right side) shows a summary
- **Click anywhere** on that box to open the PDF in a new tab
- The PDF includes all triage details, conversation transcript, and photos

## Troubleshooting

If PDF generation fails:
1. Check if `pandoc` is installed: `which pandoc`
2. Check if `xelatex` is installed: `which xelatex`
3. Check logs for errors: Look for "PDF conversion" messages
4. The system will gracefully fall back to `.md` only if PDF generation fails
