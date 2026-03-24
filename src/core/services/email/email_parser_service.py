class EmailParserService:
    @staticmethod
    def strip_reply_quotes(body: str) -> str:
        if not body:
            return body
        lines = body.splitlines()
        cut_at = len(lines)
        for i, line in enumerate(lines):
            s = line.strip()
            if s.startswith("________________________________"):
                cut_at = i; break
            if s.lower().startswith("-----original message-----"):
                cut_at = i; break
            if s.startswith("On ") and (
                "wrote:" in s or
                (i + 1 < len(lines) and "wrote:" in lines[i + 1])
            ):
                cut_at = i; break
            if s.startswith(">"):
                cut_at = i; break
        result = "\n".join(lines[:cut_at]).strip()
        return result or body
