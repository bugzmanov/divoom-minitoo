#import <Foundation/Foundation.h>
#import "Headers/ImageConvertor.h"

int main(int argc, char* argv[]) {
    @autoreleasepool {
        if (argc < 7) {
            NSLog(@"usage: %s <in.png> <out.bin> <eColor> <eType> <binType> <boardType>",
                  argv[0]);
            NSLog(@"  eColor: rgb565|rgb565A|rgb888|rgb888A");
            NSLog(@"  eType:  0=keep alpha, 1=no alpha");
            NSLog(@"  binType:0=with rotation, 1=no rotation");
            NSLog(@"  boardType:0=55X, 1=56X, 2=52X");
            return 64;
        }
        NSData* png = [NSData dataWithContentsOfFile:[NSString stringWithUTF8String:argv[1]]];
        if (!png) { NSLog(@"read failed"); return 2; }
        NSString* eColor = [NSString stringWithUTF8String:argv[3]];
        uint8_t eType    = (uint8_t)atoi(argv[4]);
        uint8_t binType  = (uint8_t)atoi(argv[5]);
        SFBoardType board = (SFBoardType)atoi(argv[6]);
        NSData* bin = [ImageConvertor EBinFromPNGData:png eColor:eColor eType:eType
                                              binType:binType boardType:board];
        if (!bin) { NSLog(@"encode returned nil"); return 3; }
        NSLog(@"encoded %lu bytes (eColor=%@ eType=%d binType=%d board=%d)",
              (unsigned long)bin.length, eColor, eType, binType, (int)board);
        [bin writeToFile:[NSString stringWithUTF8String:argv[2]] atomically:YES];
        return 0;
    }
}
