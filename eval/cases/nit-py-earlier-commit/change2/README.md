# scorer

Ranks contest entries by score.

```python
from scorer import rank
rank({"ann": 12.0, "bo": 40.5, "cy": 33.0})   # -> ["bo", "cy", "ann"]
```

Run `python -m scorer entries.csv [settings.json]` to print the ranking of a file with one `name,score` per line.
