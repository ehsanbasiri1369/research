# Multiply v1 * v2 in the binary tower field
# See https://blog.lambdaclass.com/snarks-on-binary-fields-binius/
# for introduction to how binary tower fields work
#
# The general rule is that if i = b0b1...bk in binary, then the
# index-i bit is the product of all x_i where b_i=1, eg. the
# index-5 bit (32) is x_2 * x_0
#
# Multiplication involves multiplying these multivariate polynomials
# as usual, but with the reduction rule that:
# (x_0)^2 = x_0 + 1
# (x_{i+1})^2 = x_{i+1} * x_i + 1

def binmul(v1, v2, L=None):
    if v1 < 2 or v2 < 2:
        return v1 * v2
    if L is None:
        L = 1 << (max(v1, v2).bit_length() - 1).bit_length()
    halflen = L//2
    quarterlen = L//4
    halfmask = (1 << halflen)-1

    L1, R1 = v1 & halfmask, v1 >> halflen
    L2, R2 = v2 & halfmask, v2 >> halflen

    # x_{i+1}^2 reduces to 1 + x_{i+1} * x_i
    R1R2 = binmul(R1, R2, halflen)
    R1R2_high = binmul(1 << quarterlen, R1R2, halflen)
    return (
        binmul(L1, L2, halflen) ^
        R1R2 ^
        (binmul(L1, R2, halflen) << halflen) ^
        (binmul(R1, L2, halflen) << halflen) ^
        (R1R2_high << halflen)
    )

# A wrapper object that makes it easy to work with binary fields
class BinaryFieldElement():

    def __init__(self, value):
        if isinstance(value, BinaryFieldElement):
            value = value.value
        self.value = value

    def __add__(self, other):
        othervalue = other if isinstance(other, int) else other.value
        if self.value < 256 and othervalue < 256:
            return addcache[self.value][othervalue]
        return BinaryFieldElement(self.value ^ othervalue)
    
    __sub__ = __add__

    def __neg__(self):
        return self

    def __mul__(self, other):
        othervalue = other if isinstance(other, int) else other.value
        if self.value < 256 and othervalue < 256:
            return mulcache[self.value][othervalue]
        return BinaryFieldElement(binmul(self.value, othervalue))

    def __pow__(self, other):
        if other == 0:
            return BinaryFieldElement(1)
        elif other == 1:
            return self
        elif other == 2:
            return self * self
        else:
            return self.__pow__(other % 2) * self.__pow__(other // 2) ** 2

    def inv(self):
        L = 1 << (self.value.bit_length() - 1).bit_length()
        return self ** (2**L - 2)

    def __truediv__(self, other):
        if isinstance(other, int):
            other = BinaryFieldElement(other)
        return BinaryFieldElement(binmul(self.value, other.inv().value))

    def __eq__(self, other):
        othervalue = other if isinstance(other, int) else other.value
        return self.value == othervalue

    def __repr__(self):
        return '<'+str(self.value)+'>'

    def bit_length(self):
        return 1 << (self.value.bit_length() - 1).bit_length()

    def to_bytes(self, length, byteorder):
        assert length >= (self.bit_length() + 7) // 8
        return self.value.to_bytes(length, byteorder)

    @classmethod
    def from_bytes(cls, b, byteorder):
        return cls(int.from_bytes(b, byteorder))

addcache = [[None for _ in range(256)] for _ in range(256)]
mulcache = [[None for _ in range(256)] for _ in range(256)]

for i in range(256):
    for j in range(256):
        addcache[i][j] = BinaryFieldElement(i ^ j)
        mulcache[i][j] = BinaryFieldElement(binmul(i, j))