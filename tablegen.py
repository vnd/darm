"""
Copyright (c) 2013, Jurriaan Bremer
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

* Redistributions of source code must retain the above copyright notice,
  this list of conditions and the following disclaimer.
* Redistributions in binary form must reproduce the above copyright notice,
  this list of conditions and the following disclaimer in the documentation
  and/or other materials provided with the distribution.
* Neither the name of the darm developer(s) nor the names of its
  contributors may be used to endorse or promote products derived from this
  software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
POSSIBILITY OF SUCH DAMAGE.
"""

import re


SM = [
    'hlt', 'step', 'cmp4', 'retn',
    'imm',
    'Rd', 'Rn', 'Rm', 'Ra', 'Rt', 'Rt2', 'RdHi', 'RdLo', 'Rs',
    'ARMExpandImm', 'cond', 'S', 'msb', 'lsb',
]

SM = dict((SM[_], _) for _ in xrange(len(SM)))


class Instruction(object):
    def __init__(self, fmt, bits, **macros):
        self.fmt = fmt
        self.bits = bits
        self.macros = macros

        self.name = re.split(r'\W', fmt)[0].lower()

        # A mapping of bit index to its integer value.
        self.value, off = {}, 0
        for bit in bits:
            if not isinstance(bit, int):
                off += bit.bitsize
                continue

            self.value[off] = bit
            off += 1

    def bitsize(self, off):
        """Calculates the bitsize up to offset.

        @off: Offset to calculate up to, not inclusive.
        """
        return sum(getattr(_, 'bitsize', 1) for _ in self.bits[:off])

    def __repr__(self):
        return '<Instruction %s, %r>' % (self.name, self.bits)

    def create(self, sm, lut, bitsize):
        idx, ret = 0, sm.offset()
        for bit in self.bits:
            if isinstance(bit, int):
                idx += 1
                continue

            bit.create(idx, sm, lut, bitsize)
            idx += bit.bitsize

        for macro in self.macros.values():
            macro.create(sm, lut, bitsize)

        sm.append(SM['retn'])
        return ret


class BitPattern(object):
    def __init__(self, bitsize, name):
        self.bitsize = bitsize
        self.name = name

    def __repr__(self):
        clz = self.__class__.__name__
        return '<%s %s, %d bits>' % (clz, self.name, self.bitsize)

    def create(self, idx, sm, lut, bitsize):
        pass


class Flag(BitPattern):
    def __init__(self, bitsize, name, pass_idx=False):
        BitPattern.__init__(self, bitsize, name)
        self.pass_idx = pass_idx

    def create(self, idx, sm, lut, bitsize):
        args = [self.idx] if self.pass_idx else []
        return sm.append(SM[self.name], *args)


class Register(BitPattern):
    def create(self, idx, sm, lut, bitsize):
        return sm.append(SM[self.name], bitsize-4-idx)


class Immediate(BitPattern):
    def create(self, idx, sm, lut, bitsize):
        return sm.append(SM['imm'], self.bitsize)


class Macro(object):
    def __init__(self, name):
        self.name = name

    def __call__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        return self

    def __repr__(self):
        return '<Macro %s>' % self.name

    def create(self, sm, lut, bitsize):
        assert not self.kwargs
        return sm.append(SM[self.name])


class Node(object):
    def __init__(self, parent=None):
        """Initialize a new node.

        @parent: Parent node.
        """
        self.parent = parent
        self.idx = None

        # All bit indices handled by this node or its parents.
        self.indices = []
        if parent:
            self.indices += parent.indices + [parent.idx]

        self.lut = {}
        self.leaf = []

    def insert(self, ins):
        """Insert a subnode somewhere down this node. """
        self.leaf.append(ins)

    def process(self):
        """Processes this node and creates subnodes as required."""
        bits = dict((idx, []) for idx in xrange(32))

        for ins in self.leaf:
            for idx, bit in enumerate(ins.bits):
                if not isinstance(bit, int):
                    continue

                bit_idx = ins.bitsize(idx)
                if not bit_idx in self.indices:
                    bits[bit_idx].append(ins)

        def _compare(a, b):
            ret = len(bits[b]) - len(bits[a])
            return ret if ret else a - b

        offs = sorted(bits, cmp=_compare)
        if not offs or not bits[offs[0]]:
            assert len(self.leaf) < 2
            self.leaf = self.leaf[0] if self.leaf else None
            return

        self.idx = offs[0]

        self.lut[self.idx] = Node(self), Node(self)
        for ins in self.leaf:
            if self.idx in ins.value:
                self.lut[self.idx][ins.value[self.idx]].insert(ins)

        self.lut[self.idx][0].process()
        self.lut[self.idx][1].process()
        self.leaf = None

    def __repr__(self):
        if self.leaf is None:
            return '<Node %r>' % self.lut
        return '<Node %r, %r>' % (self.lut, self.leaf)

    def dump(self, idx=0):
        for bit, (null, one) in self.lut.items():
            if null.lut or null.leaf:
                print ' '*idx, '%d: 0' % bit
                null.dump(idx+1)

            if one.lut or one.leaf:
                print ' '*idx, '%d: 1' % bit
                one.dump(idx+1)

        if self.leaf:
            print ' '*idx, '->', self.leaf.name

    def create(self, sm, lut, bitsize):
        if self.leaf:
            return self.leaf.create(sm, lut, bitsize)

        bit, (null, one) = self.lut.items()[0]

        off = sm.alloc(4)
        off2 = lut.alloc(2)

        if not null.lut and not null.leaf:
            off_null = sm.insert(SM['hlt'])
        else:
            off_null = null.create(sm, lut, bitsize)

        if not one.lut and not one.leaf:
            off_one = sm.insert(SM['hlt'])
        else:
            off_one = one.create(sm, lut, bitsize)

        sm.update(off, SM['step'], bitsize-1-bit, off2 % 256, off2 / 256)
        lut.update(off2, off_null, off_one)
        return off


class LookupTable(object):
    def __init__(self, bits):
        self.table = []
        self.bits = bits

    def offset(self):
        return len(self.table)

    def alloc(self, length):
        ret = len(self.table)
        self.table += [None for _ in xrange(length)]
        return ret

    def insert(self, value):
        assert value >= 0 and value < 2**self.bits
        if value in self.table:
            return self.table.index(value)
        ret = len(self.table)
        self.table.append(value)
        return ret

    def update(self, offset, *args):
        assert all(_ >= 0 and _ < 2**self.bits for _ in args)
        tbl_begin = self.table[:offset]
        tbl_end = self.table[offset+len(args):]
        self.table = tbl_begin + list(args) + tbl_end

    def append(self, *args):
        assert all(_ >= 0 and _ < 2**self.bits for _ in args)
        ret = len(self.table)
        self.table += args
        return ret


class Table(object):
    def __init__(self, insns, bitsize):
        self.root = Node()
        self.bitsize = bitsize

        for ins in insns:
            self.root.insert(ins)

        self.root.process()

    def __repr__(self):
        return '<Table %r>' % self.root

    def dump(self):
        self.root.dump()

    def create(self):
        sm = LookupTable(8)
        lut = LookupTable(16)
        self.root.create(sm, lut, self.bitsize)
        return sm, lut
