import macros
from macros import asm
from AST import NodeType, ASTNode
from expression import ExprNodeType, ExprNode
from typing import Dict, Optional, List
from dataclasses import dataclass

@dataclass
class SymbolInfo:
    offset_from_base: int  
    is_function: bool = False
    arg_count: int = 0
    is_loop: bool = False
    label: str = ""
    l_start: str = ""
    l_next: str = ""
    l_end: str = ""
    var_offset: int = 0

class Compiler:
    def __init__(self):
        self.scopes: List[Dict[str, SymbolInfo]] = [{}]
        self.current_stack_depth = 0
        self.label_counter = 0

    def get_symbol(self, name: str) -> Optional[SymbolInfo]:
        for scope in reversed(self.scopes):
            if name in scope:
                return scope[name]
        return None

    def declare_symbol(self, name: str, is_fn=False, args=0):
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
        macros.init()
        self._compile_node(node)
        return asm

    def _compile_node(self, node: ASTNode):
        method_name = node.node_type.name
        visitor = getattr(self, method_name, self.error)
        return visitor(node)
        
    def error(self, node):
        raise NotImplementedError(f"No compile method for {node.node_type}")

    def Loop(self, node):
        label_name = node.identifier
        var_name = node.args[0]
        
        self._compile_expr(node.children[0].expr)
        count_offset = self.current_stack_depth - 4 
        
        macros.push_value(0)
        self.current_stack_depth += 4
        
        self.enter_scope()
        var_info = self.declare_symbol(var_name)
        
        l_start = self.get_unique_label(f"{label_name}_start")
        l_next  = self.get_unique_label(f"{label_name}_next")
        l_end   = self.get_unique_label(f"{label_name}_end")
        
        loop_info = SymbolInfo(
            offset_from_base=0, 
            is_function=False, 
            arg_count=0,
            is_loop=True,
            label=label_name,
            l_start=l_start,
            l_next=l_next,
            l_end=l_end,
            var_offset=var_info.offset_from_base
        )
        self.scopes[-1][f"__loop_{label_name}"] = loop_info
        
        asm.label(l_start)
        asm.load(macros.t0, macros.stack_ptr, var_info.offset_from_base - self.current_stack_depth)
        asm.load(macros.t1, macros.stack_ptr, count_offset - self.current_stack_depth)
        asm.bge(macros.t0, macros.t1, l_end)
        
        self._compile_node(node.children[1])
        
        asm.label(l_next)
        asm.load(macros.t0, macros.stack_ptr, var_info.offset_from_base - self.current_stack_depth)
        asm.addi(macros.t0, macros.t0, 1)
        asm.store(macros.stack_ptr, var_info.offset_from_base - self.current_stack_depth, macros.t0)
        asm.jal(macros.x0, l_start)
        
        asm.label(l_end)
        self.exit_scope()
        
        macros.pop(macros.t0)
        macros.pop(macros.t0)
        self.current_stack_depth -= 8

    def LoopControl(self, node):
        target_loop = None
        for scope in reversed(self.scopes):
            key = f"__loop_{node.identifier}"
            if key in scope:
                target_loop = scope[key]
                break
                
        if not target_loop: 
            raise ValueError(f"Loop label {node.identifier} not found!")

        target_depth = target_loop.var_offset + 4 
        diff = self.current_stack_depth - target_depth

        cmd = node.args[0]
        if cmd == "end":
            if diff > 0: asm.addi(macros.stack_ptr, macros.stack_ptr, -diff)
            asm.jal(macros.x0, target_loop.l_end)
        elif cmd == "next":
            if diff > 0: asm.addi(macros.stack_ptr, macros.stack_ptr, -diff)
            asm.jal(macros.x0, target_loop.l_next)
        elif cmd == "expr":
            self._compile_expr(node.children[0].expr)
            macros.pop(macros.t0)
            self.current_stack_depth -= 4
            
            if diff > 0: asm.addi(macros.stack_ptr, macros.stack_ptr, -diff)
            
            # Write new value cleanly back to index variable
            asm.store(macros.stack_ptr, -4, macros.t0)
            asm.jal(macros.x0, target_loop.l_start)

    def Return(self, node):
        if node.children:
            child = node.children[0]
            if child.node_type == NodeType.Expression:
                self._compile_expr(child.expr)
            else:
                self._compile_node(child)
                
            macros.pop(macros.t0) 
            self.current_stack_depth -= 4
            asm.addi(macros.a0, macros.t0, 0)
        else:
            asm.addi(macros.a0, macros.x0, 0)
            
        if self.current_stack_depth > 0:
            asm.addi(macros.stack_ptr, macros.stack_ptr, -self.current_stack_depth)

        asm.jalr(macros.x0, macros.ra, 0)

    def Expression(self, node):
        if node.expr:
            self._compile_expr(node.expr)
            # Prevent standalone statement expressions from leaking memory!
            macros.pop(macros.t0)
            self.current_stack_depth -= 4

    def FieldDecl(self, node):
        child = node.children[0]
        if child.node_type == NodeType.Expression:
            self._compile_expr(child.expr)
        else:
            self._compile_node(child)
        self.declare_symbol(node.identifier)

    def Block(self, node):
        self.enter_scope()
        start_depth = self.current_stack_depth
        
        for child in node.children:
            self._compile_node(child)
            
        # Crucial scope cleanup! Protects loops.
        diff = self.current_stack_depth - start_depth
        if diff > 0:
            asm.addi(macros.stack_ptr, macros.stack_ptr, -diff)
            self.current_stack_depth = start_depth
            
        self.exit_scope()

    def Assignment(self, node):
        name = node.identifier
        if node.children and \
            node.children[0].node_type == NodeType.Block and \
            node.children[0].args:
            self._compile_function_def(name, node.children[0])
        else:
            child = node.children[0]
            if child.node_type == NodeType.Expression:
                self._compile_expr(child.expr)
            else:
                self._compile_node(child)
            self.declare_symbol(name)

    def Store(self, node):
        self._compile_expr(node.children[1].expr)
        self._compile_expr(node.children[0].expr)
        macros.pop_mem()
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
            
        asm.addi(macros.a0, macros.x0, 0)
        if self.current_stack_depth > 0:
            asm.addi(macros.stack_ptr, macros.stack_ptr, -self.current_stack_depth)
        asm.jalr(macros.x0, macros.ra, 0)
            
        self.exit_scope()
        self.current_stack_depth = old_depth
        asm.label(end_label)

    def _compile_expr(self, node: ExprNode):
        match node.type:
            case ExprNodeType.Value:
                macros.push_value(node.value.value)
                self.current_stack_depth += 4
            case ExprNodeType.Deref:
                self._compile_expr(node.left)
                macros.pop(macros.t0) 
                asm.load(macros.t1, macros.t0, 0)
                macros.push(macros.t1)
            case ExprNodeType.Identifier:
                sym = self.get_symbol(node.value.value)
                if not sym:
                    raise ValueError(f"Undefined variable: {node.value.value}")
                
                offset = (sym.offset_from_base - self.current_stack_depth) 
                asm.load(macros.t0, macros.stack_ptr, offset) 
                macros.push(macros.t0)
                self.current_stack_depth += 4

            case ExprNodeType.BinaryOp:
                self._compile_expr(node.left)
                self._compile_expr(node.right)
                
                macros.pop(macros.t1)
                macros.pop(macros.t0)
                self.current_stack_depth -= 8
                
                op_sym = node.value.value
                if op_sym == "+":
                    asm.add(macros.t0, macros.t0, macros.t1)
                elif op_sym == "-":
                    asm.sub(macros.t0, macros.t0, macros.t1)
                elif op_sym == "==":
                    asm.sub(macros.t0, macros.t0, macros.t1)
                    asm.sltiu(macros.t0, macros.t0, 1)     
                elif op_sym == "!=":
                    asm.sub(macros.t0, macros.t0, macros.t1)
                    asm.sltu(macros.t0, macros.x0, macros.t0) 
                elif op_sym == "<":
                    asm.slt(macros.t0, macros.t0, macros.t1)
                elif op_sym == ">":
                    asm.slt(macros.t0, macros.t1, macros.t0)
                elif op_sym == "<=":
                    asm.slt(macros.t0, macros.t1, macros.t0) 
                    asm.xori(macros.t0, macros.t0, 1)        
                elif op_sym == ">=":
                    asm.slt(macros.t0, macros.t0, macros.t1) 
                    asm.xori(macros.t0, macros.t0, 1)        
                
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
                
                asm.addi(macros.stack_ptr, macros.stack_ptr, size * 4)
                self.current_stack_depth += (size * 4)