#!/bin/bash
# Unix/Linux/Mac shell script to run Power BI analyzer
# Supports multiple .pbip files and batch processing

if [ -z "$1" ]; then
    cat << 'EOF'

Power BI Analyzer - Usage
=========================

Analyze a specific .pbip file:
  ./run.sh ../RecursosFuente/MyProject.pbip

Analyze all .pbip files in a folder:
  ./run.sh ../RecursosFuente/

Analyze from current folder:
  ./run.sh .

EOF
    exit 0
fi

python3 main.py "$@"
