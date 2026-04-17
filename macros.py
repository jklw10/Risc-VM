
from asm import RiscVAssembler

# Create the assembler
asm = RiscVAssembler()
x0 = 0      #register 
ra = 1      #register
t0 = 5      #register
t1 = 6      #register 
t2 = 7      #register
t3 = 28     #register
a0 = 10     #register
a7 = 17     #register

# Full standard RISC-V ABI to integer registers
reg_map = {f"x{i}": i for i in range(32)}
reg_map.update({
    "zero": 0, "ra": 1, "sp": 2, "gp": 3, "tp": 4,
    "t0": 5, "t1": 6, "t2": 7, "s0": 8, "fp": 8, "s1": 9,
    "a0": 10, "a1": 11, "a2": 12, "a3": 13, "a4": 14, "a5": 15, "a6": 16, "a7": 17,
    "s2": 18, "s3": 19, "s4": 20, "s5": 21, "s6": 22, "s7": 23, "s8": 24, "s9": 25, "s10": 26, "s11": 27,
    "t3": 28, "t4": 29, "t5": 30, "t6": 31
})#todo, define these all  somewhere like macros.py
                
#x_ret = 31 #register

#stack ptr is at 2, skip it, i should check if this is universal
stack_ptr = 2 #register, i like a little verbose
stack_start = 0x8000 #memory
stack_incr = 4 #bytes
#LOCALS = 0 #memory
#RETVAL = 1 #memory
#ARGS = 2 #memory

def init():
    #"""4b"""
    load_immediate(stack_ptr, stack_start)
    #asm.addi(stack_ptr, stack_ptr, stack_start) 

def push(reg):
    """push register to stack"""
    asm.store(stack_ptr, 0, reg)                
    asm.addi(stack_ptr, stack_ptr, stack_incr)     

def pop(reg):
    """pop from stack to register"""
    asm.addi(stack_ptr, stack_ptr, -stack_incr)  
    asm.load(reg, stack_ptr, 0)                  

def peek(reg):
    """peek stack to register"""
    asm.load(reg, stack_ptr, -stack_incr)

def load_immediate(reg, val):
    """
    Smart load: Uses ADDI for small numbers, LUI+ADDI for large ones.
    """
    if -2048 <= val <= 2047:
        asm.addi(reg, x0, val)
        return
    lo = val & 0xFFF
    hi = val >> 12
    
    if lo & 0x800:
        hi += 1
        
    asm.lui(reg, hi)
    asm.addi(reg, reg, lo)

def push_value(value):
    """push value to stack (handles large integers)"""
    load_immediate(t0, value)
    push(t0)

def push_static(addr):
    """push memory at address to stack"""
    asm.load(t0, addr, 0)
    push(t0)

def pop_static(addr):
    """pop value to address in memory"""
    pop(t0)
    asm.store(addr,0,t0)

def push_mem():
    """push value at stack to memory"""
    pop(t0)
    push_static(t0)

def pop_mem():
    """pop 2 values, first is address, second is what goes there"""
    pop(t0)
    pop(t1)
    asm.store(t0,0,t1)

#def goto(label):
#    # just use jal directly tbh.
#def if_goto(label): 
#    #bne


#def call(funcname, argCount):
#    push_static(ARGS)                          
#    push_static(LOCALS)                        
#    asm.addi(x3, stack_ptr, -(argCount*stack_incr))         
#    asm.addi(x3, x3, -(2*stack_incr))  #pushes in call 
#    asm.store(ARGS, 0, x3)                     
#    asm.jal(x_ret, funcname)  
#    #cleanup  
#    asm.addi(x3, ARGS, 0)              
#    pop(t0)
#    asm.store(ARGS, 0, t0) 
#    pop(t0)
#    asm.store(LOCALS, 0, t0)   
#    asm.addi(stack_ptr, x3, 0)      
#    push_static(RETVAL)
    
#def fun(funcname, localsCount):
#    asm.label(funcname)
#    asm.store(LOCALS, 0, stack_ptr)   
#    asm.addi(stack_ptr, stack_ptr, localsCount)   

#def ret():
#    pop_static(RETVAL)
#    asm.store(stack_ptr, 0, LOCALS) 
#    asm.jal(x0, x_ret)

#def push_args(idx):
#    """push memory args+idx to stack"""
#    asm.load(t0, ARGS, idx)
#    push(t0)
#
#def pop_args(idx):
#    """pop value to args+idx"""
#    pop(t0)
#    asm.store(ARGS,idx,t0)
    
