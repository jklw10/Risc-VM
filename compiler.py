import macros
from macros import asm
from AST import NodeType, ASTNode
from expression import ExprNodeType, ExprNode
from typing import Dict, Optional, List
from dataclasses import dataclass

@dataclass
class SymbolInfo:
    offset_from_base: int  # Absolute position from start of stack frame
    is_function: bool = False
    arg_count: int = 0

class Compiler:
    def __init__(self):
        self.scopes: List[Dict[str, SymbolInfo]] = [{}] # Stack of scopes
        self.loop_stack =[]
        #todo combine these 2, a loop is a scope.
        self.current_stack_depth = 0 # Tracks how many bytes we've pushed
        self.label_counter = 0

    def get_symbol(self, name: str) -> Optional[SymbolInfo]:
        # Search from inner scope outwards
        for scope in reversed(self.scopes):
            if name in scope:
                return scope[name]
        return None

    def declare_symbol(self, name: str, is_fn=False, args=0):
        # Declare in current scope
        info = SymbolInfo(offset_from_base=self.current_stack_depth-4,
                           is_function=is_fn, arg_count=args)
        self.scopes[-1][name] = info
        return info

    def enter_scope(self):
        self.scopes.append({})

    def exit_scope(self):
        self.scopes.pop()

    def get_unique_label(self, prefix="lbl"):
        self.label_counter += 1
        return f"{prefix}_{self.label_counter}"

    def compile(self, node: ASTNode):
        macros.init() # Setup stack pointer
        self._compile_node(node)
        return asm

    def _compile_node(self, node: ASTNode):
        method_name = node.node_type.name
        visitor = getattr(self, method_name, self.error)
        return visitor(node)
        
    def error(self, node):
        raise NotImplementedError(f"No compile method for {node.node_type}")

    def Loop(self, node, label_name):
        # 1. Compile count expression, push to stack
        self._compile_expr(node.children[0].expr)
        count_offset = self.current_stack_depth - 4 
        
        # 2. Push initial loop variable (0)
        macros.push_value(0)
        self.current_stack_depth += 4
        
        # 3. Enter Scope and register 'i'
        self.enter_scope()
        var_info = self.declare_symbol(node.identifier)
        
        # 4. Generate Labels
        l_start = self.get_unique_label(f"{label_name}_start")
        l_next  = self.get_unique_label(f"{label_name}_next")
        l_end   = self.get_unique_label(f"{label_name}_end")
        
        self.loop_stack.append({
            "label": label_name, "start": l_start, "next": l_next, "end": l_end, 
            "var_offset": var_info.offset_from_base
        })
        
        # --- LOOP START ---
        asm.label(l_start)
        asm.load(macros.t0, macros.stack_ptr, var_info.offset_from_base - self.current_stack_depth)
        asm.load(macros.t1, macros.stack_ptr, count_offset - self.current_stack_depth)
        asm.bge(macros.t0, macros.t1, l_end)  # If i >= count, break!
        
        # Compile Body
        self._compile_node(node.children[1])
        
        # --- LOOP NEXT (Standard Increment) ---
        asm.label(l_next)
        asm.load(macros.t0, macros.stack_ptr, var_info.offset_from_base - self.current_stack_depth)
        asm.addi(macros.t0, macros.t0, 1)
        asm.store(macros.stack_ptr, var_info.offset_from_base - self.current_stack_depth, macros.t0)
        asm.jal(macros.x0, l_start)
        
        # --- LOOP END ---
        asm.label(l_end)
        self.loop_stack.pop()
        self.exit_scope()
        
        # Pop 'i' and 'count' off stack to clean up memory
        macros.pop(macros.t0)
        macros.pop(macros.t0)
        self.current_stack_depth -= 8

    def LoopControl(self, node):
        # Find the requested loop
        target = next((l for l in reversed(self.loop_stack) if l["label"] == node.identifier), None)
        if not target: 
            raise ValueError(f"Loop label {node.identifier} not found!")

        cmd = node.args[0]
        if cmd == "end":
            asm.jal(macros.x0, target["end"])
        elif cmd == "next":
            asm.jal(macros.x0, target["next"])
        elif cmd == "expr":
            # 1. Evaluate the new state of 'i'
            self._compile_expr(node.children[0].expr)
            macros.pop(macros.t0)
            self.current_stack_depth -= 4
            
            # 2. Overwrite 'i' on the stack
            offset = target["var_offset"] - self.current_stack_depth
            asm.store(macros.stack_ptr, offset, macros.t0)
            
            # 3. Jump to the start of the loop (skip the standard +1!)
            asm.jal(macros.x0, target["start"])

    def Return(self, node):
        if node.children:
            # 1. Compile the return expression (pushes result to stack)
            self._compile_node(node.children[0])
            
            # 2. Pop the result into t0
            macros.pop(macros.t0) 
            
            # THE FIX: Tell the compiler we just removed 4 bytes!
            self.current_stack_depth -= 4
            
            # 3. Move return value to a0
            asm.addi(macros.a0, macros.t0, 0)
        else:
            # If void return, default to returning 0
            asm.addi(macros.a0, macros.x0, 0)
            
        # 4. Clean up the rest of the local variables from this scope
        if self.current_stack_depth > 0:
            asm.addi(macros.stack_ptr, macros.stack_ptr, -self.current_stack_depth)

        asm.jalr(macros.x0, macros.ra, 0)
        #asm.jal(macros.x0, macros.ra)

    def Expression(self, node):
        if node.expr:
            self._compile_expr(node.expr)

    def FieldDecl(self, node):
        for child in node.children:
            self._compile_node(child)
                
        self.declare_symbol(node.identifier)

    def Block(self, node):
        for child in node.children:
            self._compile_node(child)

    def Assignment(self, node):
        name = node.identifier
                
        if node.children and \
            node.children[0].node_type == NodeType.Block and \
            node.children[0].args:
            self._compile_function_def(name, node.children[0])
        else:
            for child in node.children:
                self._compile_node(child)
                    
            self.declare_symbol(name)

    def Store(self, node):
        self._compile_expr(node.children[1].expr) # Push Val (1)
        self._compile_expr(node.children[0].expr) # Push Addr (65000)
        macros.pop_mem()
                #macros.pop(macros.t0) # Addr
                #macros.pop(macros.t1) # Val
                #asm.store(macros.t0, 0, macros.t1)
        self.current_stack_depth -= 8

    def Deref(self, node):
        self._compile_expr(node.left)
        macros.pop(macros.t0) 
        asm.load(macros.t1, macros.t0, 0)
        macros.push(macros.t1)

    def Program(self, node):
        for child in node.children:
            self._compile_node(child)

    def _compile_function_def(self, name: str, block_node: ASTNode):
      
        end_label = self.get_unique_label("end_func")
        asm.jal(macros.x0, end_label)
        
        asm.label(name)
        
        old_depth = self.current_stack_depth
        self.current_stack_depth = 0  
        self.enter_scope()
        
        
        arg_offset = -4 
        for arg in reversed(block_node.args):
            info = SymbolInfo(
                offset_from_base=arg_offset, 
                is_function=False, 
                arg_count=0
            )
            self.scopes[-1][arg] = info
            
            arg_offset -= 4

        for child in block_node.children:
            self._compile_node(child)
            
        self.exit_scope()
        
        self.current_stack_depth = old_depth
        asm.label(end_label)

    def _compile_expr(self, node: ExprNode):
        match node.type:
            case ExprNodeType.Value:
                # Push immediate
                macros.push_value(node.value.value)
                self.current_stack_depth += 4
            case ExprNodeType.Deref:
                self._compile_expr(node.left)
                macros.pop(macros.t0) 
                asm.load(macros.t1, macros.t0, 0)
                macros.push(macros.t1)
            case ExprNodeType.Identifier:
                # Load variable
                sym = self.get_symbol(node.value.value)
                if not sym:
                    raise ValueError(f"Undefined variable: {node.value.value}")
                
                offset = (sym.offset_from_base - self.current_stack_depth) 
                
                asm.load(macros.t0, macros.stack_ptr, offset) 
                
                macros.push(macros.t0)
                self.current_stack_depth += 4

            case ExprNodeType.BinaryOp:
                # 1. Compile Left
                self._compile_expr(node.left)
                # 2. Compile Right
                self._compile_expr(node.right)
                
                # 3. Pop both and operate
                macros.pop(macros.t1) # Right
                macros.pop(macros.t0) # Left
                self.current_stack_depth -= 8
                
                op_sym = node.value.value
                if op_sym == "+":
                    asm.add(macros.t0, macros.t0, macros.t1)
                elif op_sym == "-":
                    asm.sub(macros.t0, macros.t0, macros.t1)
                #elif op_sym == "*":
                #    #asm.mul(macros.x1, macros.x1, macros.x2)
                #elif op_sym == "/":
                #    #asm.mul(macros.x1, macros.x1, macros.x2)
                #elif op_sym == "^":
                    #asm.mul(macros.x1, macros.x1, macros.x2)
                # ... add other ops ...
                
                macros.push(macros.t0)
                self.current_stack_depth += 4

            case ExprNodeType.Call:
                func_name = node.value.value
                
                asm.addi(macros.t0, macros.ra, 0)
                macros.push(macros.t0)
                self.current_stack_depth += 4

                for arg in node.children:
                    self._compile_expr(arg)
                
                asm.jal(macros.ra, func_name)
                
                asm.addi(macros.t2, macros.a0, 0) 

                for _ in node.children:
                     macros.pop(macros.x0) 
                     self.current_stack_depth -= 4
                
                macros.pop(macros.ra)
                self.current_stack_depth -= 4
                
                macros.push(macros.t2)
                self.current_stack_depth += 4

            case ExprNodeType.ArrayAlloc:
                size = node.value.value 

                macros.push(macros.stack_ptr) 
                self.current_stack_depth += 4
                #asm.addi(macros.t0, macros.stack_ptr, 0)
                
                asm.addi(macros.stack_ptr, macros.stack_ptr, size * 4)
                self.current_stack_depth += (size * 4)
                
                #macros.push(macros.t0)
