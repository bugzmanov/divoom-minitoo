#import <Foundation/Foundation.h>
#import "eZIPSDK.framework/Headers/ImageConvertor.h"

int main(int argc, char* argv[]) {
    @autoreleasepool {
        if (argc < 3) { NSLog(@"usage: %s <in.png> <out.ezip>", argv[0]); return 1; }
        NSString* inPath = [NSString stringWithUTF8String:argv[1]];
        NSString* outPath = [NSString stringWithUTF8String:argv[2]];
        NSData* png = [NSData dataWithContentsOfFile:inPath];
        if (!png) { NSLog(@"failed to read %@", inPath); return 2; }
        NSLog(@"input: %lu bytes", (unsigned long)png.length);

        // Args observed in BluePhotoModel: AbstractC0522n.c with ("rgb565", 1, 1, 2, 1000)
        //   → eColor="rgb565", eType=1, binType=1, boardType=2 (52X)
        NSData* bin = [ImageConvertor EBinFromPNGData:png
                                                eColor:@"rgb565"
                                                 eType:1
                                               binType:1
                                             boardType:SFBoardType52X];
        if (!bin) { NSLog(@"EBinFromPNGData returned nil"); return 3; }
        NSLog(@"output: %lu bytes ezip", (unsigned long)bin.length);
        [bin writeToFile:outPath atomically:YES];
        return 0;
    }
}
