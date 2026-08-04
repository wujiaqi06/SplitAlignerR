# ENGINE002-FIX001B Pro RECERT objects

Verify the complete unsquashed development history:

| Object | Commit |
|---|---|
| certified `v0.1.0` peeled commit | `17a0927095c7a067817bf598a2556cbe7348a6d0` |
| ENGINE001 | `93e8bf79ff6fb6b6419d794b7ef70bac702b8665` |
| ENGINE002 original | `8c0d494f57f4594ff5acfd8e02ef546fcc387f0b` |
| ENGINE002-FIX001 | `94b45820b811e95ce29c9a9c062cbf8e8bbfbbdf` |
| FIX001A final CI implementation | `086fad1b752d90819183d54ee6e9885439e06dc2` |
| FIX001A evidence base | `b96634c7f43307102714fc2e13dd8780e2126b69` |
| FIX001B SHA repair | `50eb182169ce9cd6ffaaf319fb4ad0b7f8064311` |
| FIX001B unit evidence | `0479ea0fd86d859fc69b5affd73e1a60e3aefcb6` |
| FIX001B regenerated fixtures | `65ebc05b10c40c521720c6a1716b7e84fdfcef0e` |
| FIX001B CI implementation | `83fd7ac75812a1272f31a85986abfd60a2db8ea2` |
| FIX001B Windows probe follow-up | `80c6c24a5abf82150e5fdf1426810208673c4dde` |
| FIX001B explicit digest-bound follow-up | `9588400014a65170bc7dbb718817d9f258237f9d` |
| FIX001B evidence | exact external package head |

A Git commit cannot contain its own object ID.  The final FIX001B evidence head
and tree are therefore frozen in the external handoff manifest, complete Git
bundle, ZIP manifests, and SHA-256 sidecars made after the evidence commit.

The original Pro FAIL decision and certificate are historical review inputs,
not a verdict on the repaired object.  The new Pro review must bind its verdict
to the exact final FIX001B head and tree.
