import os

class ExportService:
    @staticmethod
    def export_to_txt(results, output_path):
        """Export results to a text file."""
        try:
            with open(output_path, "w", encoding="utf-8") as f:
                for res in results:
                    line = f"[{res['start']:.1f}s - {res['end']:.1f}s]"
                    if res.get("speaker"):
                        line += f" {res['speaker']}: "
                    line += f"{res.get('text', '')}\n"
                    f.write(line)
            return True
        except Exception as e:
            print(f"TXT export error: {e}")
            return False
