import struct

# Match the Zig enum exactly
OP_HALT, OP_LOADIMM, OP_ADD, OP_SUB, OP_MUL, OP_DIV = 0, 1, 2, 3, 4, 5
OP_SLT, OP_SLTU = 6, 7
OP_AND, OP_OR, OP_XOR, OP_SLL, OP_SRL, OP_SRA = 8, 9, 10, 11, 12, 13
OP_LOAD, OP_STORE = 14, 15
OP_JMP, OP_BEQ, OP_BNE, OP_BLT, OP_BGE = 16, 17, 18, 19, 20
OP_CALL, OP_RET = 21, 22
OP_SYSCALL = 23

class VmAssembler:
    def __init__(self):
        self.code = bytearray()
        self.labels = {}
        self.fixups = {}
        self.pc = 0  # PC is now the INSTRUCTION INDEX, not byte offset!

    def _emit(self, op, r0=0, r1=0, r2=0, imm=0):
        # Pack 1+1+1+1+4 = 8 bytes total
        self.code.extend(struct.pack("<BBBBi", op, r0, r1, r2, imm))
        self.pc += 1

    def label(self, name):
        if name in self.labels: raise ValueError(f"Twice: {name}")
        self.labels[name] = self.pc
        
        # Resolve any jumps that were looking for this label
        if name in self.fixups:
            for addr in self.fixups[name]:
                # We update the `imm` (last 4 bytes) of the 8 byte instruction
                struct.pack_into("<i", self.code, addr + 4, self.pc)
            del self.fixups[name]

    def _resolve_or_record(self, label):
        if isinstance(label, int): return label
        if label in self.labels: return self.labels[label]
        
        if label not in self.fixups: self.fixups[label] = []
        # Record the BYTE address of the instruction so we can inject the imm later
        self.fixups[label].append(len(self.code))
        return 0 

    # --- INSTRUCTIONS BECOME TRIVIAL ---
    def addi(self, rd, rs1, imm): 
        # Convert to a LoadImm and Add, or natively support Addi
        self.load_immediate(31, imm) # use temp register 31
        self._emit(OP_ADD, rd, rs1, 31, 0)
        
    def add(self, rd, rs1, rs2): 
        self._emit(OP_ADD, rd, rs1, rs2, 0)

    def store(self, rs1, offset, rs2): 
        self._emit(OP_STORE, 0, rs1, rs2, offset)

    def load(self, rd, rs1, offset):
        self._emit(OP_LOAD, rd, rs1, 0, offset)

    def load_immediate(self, rd, imm):
        self._emit(OP_LOADIMM, rd, 0, 0, imm)

    def beq(self, rs1, rs2, label):
        target_pc = self._resolve_or_record(label)
        self._emit(OP_BEQ, 0, rs1, rs2, target_pc)

    def syscall(self, syscall_id):
        self._emit(OP_SYSCALL, 0, 0, 0, syscall_id)