import { Root } from "./root.js";
import { NumberValue, StringValue } from "../types/primitives";
import { ResolvedTextField } from "../types/types.js";
export declare class Slider extends Root {
    #private;
    accessor value: NumberValue | null;
    accessor minValue: number;
    accessor maxValue: number;
    accessor label: StringValue | null;
    accessor inputType: ResolvedTextField["type"] | null;
    static styles: any[];
    render(): any;
}
//# sourceMappingURL=slider.d.ts.map