# scorer

Ranks contest entries by score.

```python
from scorer import rank
rank([12.0, 40.5, 33.0])   # -> [1, 2, 0]
```

Run `python -m scorer entries.txt` to print the ranking of a file with one score per line.
