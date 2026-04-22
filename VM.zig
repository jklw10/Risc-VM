const std = @import("std");

pub const Op = enum(u8) {
    Halt = 0, LoadImm, Add, Sub, Mul, Div,
    Load, Store, Call, Ret, Bge, Blt, Syscall
};

// 8 Bytes total per instruction! Fits naturally in memory.
pub const Instruction = packed struct {
    op: Op,
    r0: u8,
    r1: u8,
    r2: u8,
    imm: i32,
};

pub const VmState = extern struct {
    regs: [32]i32,
    pc: u32,             
    memory: [65536]u8, // Unified 64KB memory!
    halted: bool,
};

inline fn step(vm: *VmState) void {
    // 1. Fetch 8 bytes from unified memory and cast to Instruction
    const raw_inst = std.mem.readInt(u64, vm.memory[vm.pc .. vm.pc+8][0..8], .little);
    const inst: Instruction = @bitCast(raw_inst);
    
    // Advance PC by 8 bytes (size of instruction)
    vm.pc += 8; 

    switch (inst.op) {
        .LoadImm => vm.regs[inst.r0] = inst.imm,
        .Add => vm.regs[inst.r0] = vm.regs[inst.r1] +% vm.regs[inst.r2],
        
        // Memory Accesses (using r1 as base pointer, imm as offset)
        .Load => {
            const addr = @as(u16, @truncate(@as(u32, @bitCast(vm.regs[inst.r1] +% inst.imm))));
            vm.regs[inst.r0] = std.mem.readInt(i32, vm.memory[addr..][0..4], .little);
        },
        .Store => {
            const addr = @as(u16, @truncate(@as(u32, @bitCast(vm.regs[inst.r1] +% inst.imm))));
            std.mem.writeInt(i32, vm.memory[addr..][0..4], vm.regs[inst.r2], .little);
        },

        // Control Flow
        .Call => {
            vm.regs[inst.r0] = @bitCast(vm.pc); // Save return address (already +8)
            vm.pc = @as(u32, @bitCast(vm.regs[inst.r1])); // Jump to register address
        },
        .Ret => vm.pc = @as(u32, @bitCast(vm.regs[inst.r1])),
        
        .Bge => if (vm.regs[inst.r1] >= vm.regs[inst.r2]) { vm.pc = @bitCast(inst.imm); },
        .Blt => if (vm.regs[inst.r1] < vm.regs[inst.r2]) { vm.pc = @bitCast(inst.imm); },

        // Syscalls route straight to Host OS via Zig!
        .Syscall => {
            const a0 = vm.regs[10]; // fd
            const a1 = @as(u16, @truncate(@as(u32, @bitCast(vm.regs[11])))); // buffer ptr
            const a2 = @as(u16, @truncate(@as(u32, @bitCast(vm.regs[12])))); // size
            
            switch (inst.imm) {
                0 => vm.halted = true,
                // Syscall 1: Print Integer
                1 => std.debug.print("{d}\n", .{a0}), 
                // Syscall 2: Write to file descriptor (mapping directly to host!)
                2 => {
                    if (a0 == 1) { // stdout
                        std.io.getStdOut().writer().writeAll(vm.memory[a1 .. a1+a2]) catch {};
                    }
                },
                else => vm.halted = true,
            }
        },
        else => {},
    }
}