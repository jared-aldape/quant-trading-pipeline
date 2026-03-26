#!/usr/bin/env python3
"""
QUANT OS DATABASE SCHEMA AUDIT & SNAPSHOT GENERATOR
Comprehensive DuckDB introspection and reporting tool.

Usage:
    python db_schema_snapshot.py [db_path]
    
Output:
    Generates: db_schema_snapshot.txt (detailed report)
"""

import duckdb
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any
import sys

class DatabaseAuditor:
    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self.report = {}
        self.errors = []
        
    def run_audit(self) -> Dict[str, Any]:
        """Run complete database audit."""
        print(f"🔍 Auditing database: {self.db_path}")
        
        if not self.db_path.exists():
            self.errors.append(f"Database file not found: {self.db_path}")
            return {"status": "ERROR", "errors": self.errors}
        
        try:
            con = duckdb.connect(str(self.db_path), read_only=True)
            
            # Collect metadata
            self.report = {
                "timestamp": datetime.now().isoformat(),
                "db_path": str(self.db_path),
                "db_size_mb": self.db_path.stat().st_size / (1024 * 1024),
                "tables": self._audit_tables(con),
                "views": self._audit_views(con),
                "sequences": self._audit_sequences(con),
                "data_quality": self._check_data_quality(con),
                "errors": self.errors
            }
            
            con.close()
            return self.report
            
        except Exception as e:
            self.errors.append(f"Audit failed: {str(e)}")
            return {"status": "ERROR", "errors": self.errors}
    
    def _audit_tables(self, con: duckdb.DuckDBPyConnection) -> Dict[str, Any]:
        """Audit all tables."""
        tables = {}
        
        try:
            table_names = con.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_type='BASE TABLE' ORDER BY table_name"
            ).fetchall()
            
            for (table_name,) in table_names:
                try:
                    tables[table_name] = self._audit_table(con, table_name)
                except Exception as e:
                    self.errors.append(f"Error auditing table {table_name}: {str(e)}")
        
        except Exception as e:
            self.errors.append(f"Failed to list tables: {str(e)}")
        
        return tables
    
    def _audit_table(self, con: duckdb.DuckDBPyConnection, table_name: str) -> Dict[str, Any]:
        """Audit a single table."""
        info = {
            "columns": [],
            "row_count": 0,
            "size_mb": 0.0,
            "primary_key": None,
            "indexes": [],
            "sample_data": []
        }
        
        # Row count
        try:
            row_count = con.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
            info["row_count"] = row_count
        except Exception as e:
            self.errors.append(f"Could not count rows in {table_name}: {e}")
        
        # Column info
        try:
            cols = con.execute(f"PRAGMA table_info('{table_name}')").fetchall()
            for col in cols:
                col_name, col_type = col[1], col[2]
                info["columns"].append({
                    "name": col_name,
                    "type": col_type
                })
        except Exception as e:
            self.errors.append(f"Could not get columns for {table_name}: {e}")
        
        # Sample data (first 3 rows)
        try:
            if info["row_count"] > 0:
                sample = con.execute(f"SELECT * FROM {table_name} LIMIT 3").fetchall()
                col_names = [c["name"] for c in info["columns"]]
                
                for row in sample:
                    row_dict = {}
                    for i, val in enumerate(row):
                        if i < len(col_names):
                            # Convert to string for JSON serialization
                            if val is None:
                                row_dict[col_names[i]] = None
                            elif isinstance(val, (datetime, type(datetime.now()))):
                                row_dict[col_names[i]] = str(val)
                            else:
                                row_dict[col_names[i]] = str(val)
                    info["sample_data"].append(row_dict)
        except Exception as e:
            self.errors.append(f"Could not fetch sample data from {table_name}: {e}")
        
        return info
    
    def _audit_views(self, con: duckdb.DuckDBPyConnection) -> Dict[str, Any]:
        """Audit all views."""
        views = {}
        
        try:
            view_names = con.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_type='VIEW' ORDER BY table_name"
            ).fetchall()
            
            for (view_name,) in view_names:
                views[view_name] = {
                    "type": "VIEW",
                    "exists": True
                }
        except Exception as e:
            self.errors.append(f"Failed to audit views: {str(e)}")
        
        return views
    
    def _audit_sequences(self, con: duckdb.DuckDBPyConnection) -> List[str]:
        """Audit sequences."""
        sequences = []
        
        try:
            # DuckDB doesn't have information_schema.sequences, skip this
            pass
        except Exception as e:
            self.errors.append(f"Failed to audit sequences: {str(e)}")
        
        return sequences
    
    def _check_data_quality(self, con: duckdb.DuckDBPyConnection) -> Dict[str, Any]:
        """Check data quality issues."""
        quality = {
            "null_checks": {},
            "duplicate_checks": {},
            "issues": []
        }
        
        try:
            table_names = con.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_type='BASE TABLE'"
            ).fetchall()
            
            for (table_name,) in table_names:
                try:
                    # Check for NULLs
                    cols = con.execute(f"PRAGMA table_info('{table_name}')").fetchall()
                    
                    for col in cols:
                        col_name = col[1]
                        try:
                            null_count = con.execute(
                                f"SELECT COUNT(*) FROM {table_name} WHERE {col_name} IS NULL"
                            ).fetchone()[0]
                            
                            if null_count > 0:
                                quality["null_checks"][f"{table_name}.{col_name}"] = null_count
                        except:
                            pass
                
                except Exception as e:
                    quality["issues"].append(f"Quality check failed for {table_name}: {e}")
        
        except Exception as e:
            quality["issues"].append(f"Data quality audit failed: {e}")
        
        return quality
    
    def generate_text_report(self) -> str:
        """Generate human-readable text report."""
        if not self.report:
            return "No report data available"
        
        lines = []
        lines.append("=" * 100)
        lines.append("QUANT OS DATABASE SCHEMA AUDIT & SNAPSHOT")
        lines.append(f"Generated: {self.report['timestamp']}")
        lines.append("=" * 100)
        
        lines.append(f"\nDATABASE: {self.report['db_path']}")
        lines.append(f"Size: {self.report['db_size_mb']:.2f} MB")
        
        # Tables
        lines.append("\n" + "=" * 100)
        lines.append("TABLES")
        lines.append("=" * 100)
        
        for table_name, table_info in sorted(self.report["tables"].items()):
            lines.append(f"\n[{table_name}]")
            lines.append(f"  Rows: {table_info['row_count']:,}")
            lines.append(f"  Columns: {len(table_info['columns'])}")
            
            # Column details
            lines.append("  Schema:")
            for col in table_info['columns']:
                lines.append(f"    - {col['name']:<30} {col['type']}")
            
            # Sample data
            if table_info['sample_data']:
                lines.append("  Sample Data (first 3 rows):")
                for i, row in enumerate(table_info['sample_data'], 1):
                    lines.append(f"    Row {i}:")
                    for key, val in row.items():
                        lines.append(f"      {key}: {val}")
        
        # Views
        if self.report["views"]:
            lines.append("\n" + "=" * 100)
            lines.append("VIEWS")
            lines.append("=" * 100)
            for view_name in sorted(self.report["views"].keys()):
                lines.append(f"  {view_name}")
        
        # Data Quality
        lines.append("\n" + "=" * 100)
        lines.append("DATA QUALITY CHECKS")
        lines.append("=" * 100)
        
        if self.report["data_quality"]["null_checks"]:
            lines.append("\nColumns with NULL values:")
            for col, count in sorted(self.report["data_quality"]["null_checks"].items()):
                lines.append(f"  {col}: {count} NULLs")
        else:
            lines.append("\nNo NULL values detected.")
        
        if self.report["data_quality"]["issues"]:
            lines.append("\nQuality Issues:")
            for issue in self.report["data_quality"]["issues"]:
                lines.append(f"  ⚠️ {issue}")
        
        # Errors
        if self.report["errors"]:
            lines.append("\n" + "=" * 100)
            lines.append("AUDIT ERRORS")
            lines.append("=" * 100)
            for error in self.report["errors"]:
                lines.append(f"  ❌ {error}")
        
        lines.append("\n" + "=" * 100)
        lines.append("END OF REPORT")
        lines.append("=" * 100)
        
        return "\n".join(lines)
    
    def save_report(self, output_path: str = "db_schema_snapshot.txt") -> str:
        """Save report to file."""
        text_report = self.generate_text_report()
        
        output_file = Path(output_path)
        # Use utf-8 encoding to handle emojis
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(text_report)
        
        # Also save JSON version
        json_path = output_file.with_suffix('.json')
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(self.report, f, indent=2, default=str)
        
        print(f"\n✅ Reports saved:")
        print(f"   Text: {output_file}")
        print(f"   JSON: {json_path}")
        
        return str(output_file)
    
    def print_summary(self):
        """Print brief summary to console."""
        if not self.report:
            print("No report data available")
            return
        
        print(f"\n📊 SCHEMA SUMMARY")
        print(f"{'='*60}")
        print(f"Database: {self.report['db_path']}")
        print(f"Size: {self.report['db_size_mb']:.2f} MB")
        print(f"Tables: {len(self.report['tables'])}")
        print(f"Views: {len(self.report['views'])}")
        print(f"\nTABLE SUMMARY:")
        
        for table_name, table_info in sorted(self.report["tables"].items()):
            print(f"  {table_name:<30} {table_info['row_count']:>10,} rows  {len(table_info['columns']):>3} cols")
        
        if self.report["errors"]:
            print(f"\n⚠️ ERRORS: {len(self.report['errors'])}")
            for error in self.report["errors"][:5]:
                print(f"   - {error}")
            if len(self.report["errors"]) > 5:
                print(f"   ... and {len(self.report['errors'])-5} more")


def main():
    """Main entry point."""
    if len(sys.argv) > 1:
        db_path = sys.argv[1]
    else:
        # Try to detect default paths
        possible_paths = [
            "data/quant_strategy.duckdb",
            "./data/quant_strategy.duckdb",
            "/home/ubuntu/QUANT-OS/data/quant_strategy.duckdb",
        ]
        
        db_path = None
        for path in possible_paths:
            if Path(path).exists():
                db_path = path
                break
        
        if not db_path:
            print("❌ Database file not found. Usage: python db_schema_snapshot.py [db_path]")
            sys.exit(1)
    
    auditor = DatabaseAuditor(db_path)
    auditor.run_audit()
    auditor.print_summary()
    auditor.save_report()


if __name__ == "__main__":
    main()