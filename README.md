# Risc-VM
A tiny RISC-V emulator. system calls aren't real, or rather are sandboxed, 1 to print, 2 to write std, 3 to read std

if you want to build the zig to dll yourself you can just run
zig build-lib cpu.zig -dynamic

test programs run if you just run
python run_vm.py <program_path.bin>
