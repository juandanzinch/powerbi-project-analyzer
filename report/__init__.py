"""
Power BI Report Generation Module.

Provides specialized generators for:
- Technical documentation (TECHNICAL_DOCUMENTATION.md)
- Extended documentation (powerbi_analysis_TIMESTAMP.md)
- Compliance reports (compliance_report.md)
"""

from .base_documentation_generator import BaseDocumentationGenerator, DocPaths
from .technical_documentation_generator import TechnicalDocumentationGenerator
from .extended_documentation_generator import ExtendedDocumentationGenerator
from .compliance_report_generator import ComplianceReportGenerator

__all__ = [
    "BaseDocumentationGenerator",
    "DocPaths",
    "TechnicalDocumentationGenerator",
    "ExtendedDocumentationGenerator",
    "ComplianceReportGenerator",
]

