
my_loop =[10] : i {
    
    // Memory[65000] += 1
    ptr = 65000;
    val = [ptr];
    [ptr] = val + 1;
    
    //loop posing as if
    fake_if = [i == 2]: _ {
       my_loop : i + 5; 
    }
};