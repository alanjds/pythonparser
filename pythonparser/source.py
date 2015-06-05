"""
The :mod:`source` module concerns itself with manipulating
buffers of source code: creating ranges of characters corresponding
to a token, combining these ranges, extracting human-readable
location information and original source from a range.
"""

from __future__ import absolute_import, division, print_function, unicode_literals
import bisect

class Buffer:
    """
    A buffer containing source code and location information.

    :ivar source: (string) source code
    :ivar name: (string) input filename or another description
        of the input (e.g. ``<stdin>``).
    :ivar line: (integer) first line of the input
    """
    def __init__(self, source, name="<input>", first_line=1):
        self.source = source
        self.name = name
        self.first_line = first_line
        self._line_begins = None

    def __repr__(self):
        return "Buffer(\"%s\")" % self.name

    def source_line(self, lineno):
        """
        Returns line ``lineno`` from source, taking ``first_line`` into account,
        or raises :exc:`IndexError` if ``lineno`` is out of range.
        """
        line_begins = self._extract_line_begins()
        lineno = lineno - self.first_line
        if lineno >= 0 and lineno + 1 < len(line_begins):
            first, last = line_begins[lineno:lineno + 2]
            return self.source[first:last]
        elif lineno >= 0 and lineno < len(line_begins):
            return self.source[line_begins[-1]:]
        else:
            raise IndexError

    def decompose_position(self, offset):
        """
        Returns a ``line, column`` tuple for a character offset into the source,
        orraises :exc:`IndexError` if ``lineno`` is out of range.
        """
        line_begins = self._extract_line_begins()
        lineno = bisect.bisect_right(line_begins, offset) - 1
        if offset >= 0 and offset <= len(self.source):
            return lineno + self.first_line, offset - line_begins[lineno]
        else:
            raise IndexError

    def _extract_line_begins(self):
        if self._line_begins:
            return self._line_begins

        self._line_begins = [0]
        index = None
        while True:
            index = self.source.find("\n", index) + 1
            if index == 0:
                return self._line_begins
            self._line_begins.append(index)

class Range:
    """
    Location of an exclusive range of characters [*begin_pos*, *end_pos*)
    in a :class:`Buffer`.

    :ivar begin_pos: (integer) offset of the first character
    :ivar end_pos: (integer) offset of the character before the last
    """
    def __init__(self, source_buffer, begin_pos, end_pos):
        self.source_buffer = source_buffer
        self.begin_pos = begin_pos
        self.end_pos = end_pos

    def __repr__(self):
        """
        Returns a human-readable representation of this range.
        """
        return "Range(\"%s\", %d, %d)" % \
            (self.source_buffer.name, self.begin_pos, self.end_pos)

    def begin(self):
        """
        Returns a zero-length range located just before the beginning of this range.
        """
        return Range(self.source_buffer, self.begin_pos, self.begin_pos)

    def end(self):
        """
        Returns a zero-length range located just after the end of this range.
        """
        return Range(self.source_buffer, self.end_pos, self.end_pos)

    def size(self):
        """
        Returns the amount of characters spanned by the range.
        """
        return self.end_pos - self.begin_pos

    def column(self):
        """
        Returns a zero-based column number of the beginning of this range.
        """
        line, column = self.source_buffer.decompose_position(self.begin_pos)
        return column

    def column_range(self):
        """
        Returns a [*begin*, *end*) tuple describing the range of columns spanned
        by this range.
        """
        return self.begin().column(), self.end().column()

    def line(self):
        """
        Returns the line number of the beginning of this range.
        """
        line, column = self.source_buffer.decompose_position(self.begin_pos)
        return line

    def join(self, other):
        """
        Returns the smallest possible range spanning both this range and other.
        Raises :exc:`ValueError` if the ranges do not belong to the same
        :class:`Buffer`.
        """
        if self.source_buffer != other.source_buffer:
            raise ValueError
        return Range(self.source_buffer,
                     min(self.begin_pos, other.begin_pos),
                     max(self.end_pos, other.end_pos))

    def source(self):
        """
        Returns the source code covered by this range.
        """
        return self.source_buffer.source[self.begin_pos:self.end_pos]

    def source_line(self):
        """
        Returns the line of source code containing the beginning of this range.
        """
        return self.source_buffer.source_line(self.line())

    def __str__(self):
        """
        Returns a Clang-style string representation of the beginning of this range.
        """
        return "%s:%d:%d-%d" % (self.source_buffer.name,
                                self.line(), self.column() + 1, self.end().column() + 1)

    def __eq__(self, other):
        """
        Returns true if the ranges have the same source buffer, start and end position.
        """
        return (type(self) == type(other) and
            self.source_buffer == other.source_buffer and
            self.begin_pos == other.begin_pos and
            self.end_pos == other.end_pos)

    def __ne__(self, other):
        """
        Inverse of :meth:`__eq__`.
        """
        return not (self == other)

class RewriterConflict(Exception):
    """
    An exception that is raised when two ranges supplied to a rewriter overlap.

    :ivar first: (:class:`Range`) first overlapping range
    :ivar second: (:class:`Range`) second overlapping range
    """

    def __init__(self, first, second):
        self.first, self.second = first, second
        exception.__init__(self, "Ranges %s and %s overlap" % (repr(first), repr(second)))

class Rewriter:
    """
    The :class:`Rewriter` class rewrites source code: performs bulk modification
    guided by a list of ranges and  code fragments replacing their original
    content.

    :ivar buffer: (:class:`Buffer`) buffer
    """

    def __init__(self, buffer):
        self.buffer = buffer
        self.ranges = []

    def replace(self, range, replacement):
        """Remove `range` and replace it with string `replacement`."""
        self.ranges.append((range, replacement))

    def remove(self, range):
        """Remove `range`."""
        self.replace(range, "")

    def insert_before(self, range, text):
        """Insert `text` before `range`."""
        self.replace(range.begin(), text)

    def insert_after(self, range, text):
        """Insert `text` after `range`."""
        self.replace(range.end(), text)

    def rewrite(self):
        """Return the rewritten source. May raise :class:`RewriterConflict`."""
        self._sort()
        self._check()

        rewritten, pos = [], 0
        for range, replacement in self.ranges:
            rewritten.append(self.buffer.source[pos:range.begin_pos])
            rewritten.append(replacement)
            pos = range.end_pos
        rewritten.append(self.buffer.source[pos:])

        return Buffer("".join(rewritten), self.buffer.name, self.buffer.first_line)

    def _sort(self):
        self.ranges.sort(key=lambda x: x[0].begin_pos)

    def _check(self):
        for (fst, _), (snd, _) in zip(self.ranges, self.ranges[1:]):
            if snd.begin_pos < fst.end_pos:
                raise RewriterConflict(fst, snd)