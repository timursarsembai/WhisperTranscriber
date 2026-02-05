import os

class ExportService:
    @staticmethod
    def export_to_txt(results, output_path):
        """Export results to a text file."""
        try:
            with open(output_path, "w", encoding="utf-8") as f:
                for res in results:
                    f.write(f"[{res['start']:.1f}s - {res['end']:.1f}s] {res['text']}\n")
            return True
        except Exception as e:
            print(f"TXT export error: {e}")
            return False
