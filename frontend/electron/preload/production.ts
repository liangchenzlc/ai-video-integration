import { z } from "zod";
import { checked } from "./projects";
import {
  productionRoutes,
  chooseTargetSchema,
  chosenTargetSchema,
  type ProductionBridge,
} from "../shared/production";

export const productionBridge = Object.freeze({
  ...Object.fromEntries(
    Object.entries(productionRoutes).map(([name, route]) => [
      name,
      (input: unknown) =>
        checked(
          `production:${name}`,
          input,
          route.input as z.ZodType,
          route.output as z.ZodType,
        ),
    ]),
  ),
  chooseTarget: (input: unknown) =>
    checked(
      "production:chooseTarget",
      input,
      chooseTargetSchema,
      chosenTargetSchema,
    ),
}) as ProductionBridge;
