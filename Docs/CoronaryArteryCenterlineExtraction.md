# Tutorial: Coronary artery centerline extraction

This tutorial walks through segmenting a coronary artery from a CT angiogram (CTA) and extracting its centerline, using the modules of this extension. The right coronary artery (RCA) is used as the example, but the same workflow applies to any single vessel branch.

It is an updated version of the original *VMTK in 3D Slicer* tutorial written by Daniel Haehn (see [Credits](#credits)). The overall pipeline is unchanged - enhance tubular structures, segment the lumen with a level set, then compute the centerline - but the module names and parameters have been brought in line with current Slicer versions, and centerline extraction now uses the much faster [Extract Centerline](ExtractCenterline.md) module.

## Pipeline overview

| Step | Module | Input | Output |
|---|---|---|---|
| 1 | *Crop volume* (Slicer core) | CTA volume | subvolume around the vessel |
| 2 | [Vesselness Filtering](VesselnessFiltering.md) | subvolume | vesselness volume |
| 3 | [Level Set Segmentation](LevelSetSegmentation.md) | subvolume + vesselness volume | lumen labelmap and surface model |
| 4 | [Extract Centerline](ExtractCenterline.md) | surface model | centerline model and curve, with radius at each point |

## Step 1: Crop the volume

A full coronary CTA (in the original tutorial: 512x512x276 voxels, 0.37x0.37x0.4 mm spacing) is much larger than needed for a single artery. Use the *Crop volume* module to extract a subvolume containing the vessel of interest (the original tutorial worked on a 293x285x194 subvolume).

This is worth doing before anything else: both vesselness filtering and level set segmentation scale with the number of voxels, and cropping turns computations that take minutes into computations that take seconds.

## Step 2: Enhance the vessels

Open the [Vesselness Filtering](VesselnessFiltering.md) module.

1. Select the cropped subvolume as `Input Volume`.
2. Place a `Seed point` in the middle of the proximal RCA.
3. Click `Preview` and inspect the result in the slice views. By default the diameter range and contrast are estimated automatically from the image around the seed point.
4. If the automatic values do not enhance the artery well, release the `Compute vessel diameters and contrast from seed point` toggle in the *Advanced* section and set `Minimum vessel diameter` and `Maximum vessel diameter` manually. The original tutorial used a diameter range of 1.0 to 5.0 mm for the RCA, which for 0.37 mm spacing corresponds to roughly 3 to 14 voxels. Note that the current module specifies diameters in **voxels**, not millimeters.
5. Click `Start` to filter the whole subvolume.

The result is a volume where the coronary arteries are bright and most other structures are dark. It is not a segmentation - it is the input that makes the next step robust.

## Step 3: Segment the lumen

Open the [Level Set Segmentation](LevelSetSegmentation.md) module.

1. Select the cropped subvolume as `Input Volume` and the vesselness volume from step 2 as `Vesselness Volume`. The original image must be used as input volume, because the surface evolution relies on the real image gradients.
2. Create a `Seeds` point list and place one point at the ostium of the RCA and one point at the distal end of the segment to be captured. Only the first and last points of the list are used - they are the two ends of the branch, and the initialization propagates fronts from both towards each other.
3. Optionally create a `Stoppers` point list and place points where the segmentation must not go, for example in an adjacent cardiac chamber or vein.
4. Adjust `Thresholding` so that the artery is continuously highlighted between the two seeds without merging into neighbouring structures. Click `Preview` to check the initialization result quickly - this runs the initialization only, skipping the evolution.
5. Click `Start` to run initialization followed by evolution and produce the `Output Labelmap` and `Output Model`.

The evolution parameters are hidden until `Show Advanced Segmentation Properties` is checked. The values used in the original tutorial for the RCA were a threshold of 206 (this is an intensity value specific to that dataset - always set the threshold from the histogram of your own image), inflation 30, curvature 40, attraction to gradient 100, and 10 iterations. Note that the module defaults today are inflation 0, curvature 70, attraction 50, 10 iterations; start from the defaults and only adjust if the result is visibly wrong.

Inspect the resulting model and labelmap in the 3D and slice views before continuing. Errors introduced here - a leak into a chamber, or a branch that closed off prematurely - propagate directly into the centerline.

## Step 4: Extract the centerline

Open the [Extract Centerline](ExtractCenterline.md) module. The original tutorial used the legacy *VMTKCenterlines* module, which required manually capping the model with a "Prepare Model" step and then placing source and target fiducials. That preparation is no longer needed.

1. Select the model from step 3 as `Surface`. (A segmentation node can be used directly as well.)
2. Create an `Endpoints` point list and place a point at each end of the vessel. Designate the inlet - the ostium - by making that control point *unselected*; the remaining points are treated as outlets. The flow direction determines the shape of the centerline at branching points, so this designation matters whenever the segmented surface contains a bifurcation. The `Auto-detect` button can place the endpoints for you.
3. Select a `Centerline model` output to get the centerline as a model, whose points carry the maximum inscribed sphere radius in a `Radius` point data array. Select a `Centerline curve` output to get the branches split into separate markups curve nodes, and a `Quantification results` table to get length, average radius, curvature, torsion, and tortuosity per branch.
4. Optionally select a `Voronoi diagram` output. This surface, similar to a medial surface, is what the method searches for paths between endpoints. It is useful both as a quality check and as a surface on which endpoints can be placed robustly.

Preprocessing is enabled by default and simplifies the input mesh to about 5000 points, which is what keeps the computation in the range of seconds rather than minutes. See the [Extract Centerline](ExtractCenterline.md) documentation for the preprocessing and mesh error check options.

Typical follow-up steps: measure the lumen along the centerline with [Cross-Section Analysis](CrossSectionAnalysis.md), split a bifurcated segment into individual branches with [Branch clipper](BranchClipper.md), or clip the vessel normal to the centerline with [Clip vessel](ClipVessel.md).

## Accuracy of this workflow

The original tutorial evaluated the RCA result against an expert segmentation using the Rotterdam Coronary Artery Algorithm Evaluation Framework (Schaap et al. 2009):

| Measure | Value | Score | Meaning |
|---|---|---|---|
| Overlap OV | 0.911 | 45.97 | 91% overlap with the expert centerline |
| Overlap OF | 0.837 | 48.35 | 83% overlap up to the first error |
| Overlap OT | 0.911 | 45.72 | 91% overlap in clinically relevant regions (diameter >= 1.5 mm) |
| Accuracy AI | 0.307 | 45.00 | average distance of about 0.3 mm from the expert centerline |

These numbers describe one vessel in one dataset with the parameters listed above, so treat them as an indication of what the pipeline can achieve rather than as a general performance figure.

## Credits

The original tutorial, *VMTK in 3D Slicer Tutorial: Coronary Artery Centerline Extraction*, was written by Daniel Haehn (University of Heidelberg), with acknowledgments to Luca Antiga (Mario Negri Institute) and Steve Pieper (Isomics Inc.). It is archived at
https://www.slicer.org/wiki/Modules:VMTK_in_3D_Slicer_Tutorial:_Coronary_Artery_Centerline_Extraction
and still contains the original screenshots of each step, though the module user interfaces shown there are from Slicer 3 and differ from current versions.

## References

- Antiga, L.; Piccinelli, M.; Botti, L.; Ene-Iordache, B.; Remuzzi, A. & Steinman, D. A. "An image-based modeling framework for patient-specific computational hemodynamics". *Medical & Biological Engineering & Computing*, 2008, 46, 1097-1112.
- Caselles, V.; Kimmel, R. & Sapiro, G. "Geodesic active contours". *Proc. Fifth International Conference on Computer Vision*, 1995, 694-699.
- Sato, Y.; Nakajima, S.; Shiraga, N.; Atsumi, H.; Yoshida, S.; Koller, T.; Gerig, G. & Kikinis, R. "Three-dimensional multi-scale line filter for segmentation and visualization of curvilinear structures in medical images". *Medical Image Analysis*, 1998, 2(2), 143-168.
- Schaap, M. et al. "Standardized Evaluation Methodology and Reference Database for Evaluating Coronary Artery Centerline Extraction Algorithms". *Medical Image Analysis*, 2009, 13(5), 701-714.
- Sethian, J. A. *Level Set Methods and Fast Marching Methods*. Cambridge University Press, 1999.
