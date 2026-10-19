@protocol GaugeRule
- (long)normalize:(long)value;
@end

__attribute__((objc_root_class))
@interface Gauge <GaugeRule> { long _base; }
@property(assign) long base;
- (long)normalize:(long)value;
@end

@implementation Gauge
@synthesize base = _base;
- (long)normalize:(long)value { return value + _base; }
@end

@interface Gauge (Extra)
- (long)offset;
@end

@implementation Gauge (Extra)
- (long)offset { return 128; }
@end
