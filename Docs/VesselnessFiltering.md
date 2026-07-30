# Vesselness Filtering

This module increases the brightness of tubular structures in an image and suppresses other shapes (plates and blobs). The result is not a segmentation, but a *vesselness* volume that can be used as input of the [Level Set Segmentation](LevelSetSegmentation.md) module, or simply to make vessels easier to see before segmenting them with Segment Editor.

The filter computes a multiscale vesselness measure from the eigenvalues of the Hessian of the image, as described by Sato et al. and Frangi et al. Because the response depends on the size of the structure, the filter is evaluated at several scales between a minimum and a maximum vessel diameter and the strongest response is kept. This makes it possible to enhance a vessel that tapers along its length, such as a coronary artery.

## Inputs and outputs

- `Input Volume`: the original image, typically a contrast-enhanced CT or MR angiogram. Do not use an already filtered image as input.
- `Seed point`: a markups point placed in the middle of the largest vessel of interest. It defines where the preview is computed, and it is also used for automatic estimation of the filtering parameters.
- `Output Volume`: the computed vesselness volume. Voxel values are in the 0..1 range, where higher values mean a stronger tubular response.

## Recommended workflow

1. Reduce the size of the input image to the region of interest (using *Crop volume* module). Vesselness filtering of a full CT angiogram takes several minutes, while a cropped subvolume takes seconds. This step alone accounts for most of the speed difference compared to older versions of this tutorial workflow.
2. Select the input volume and place a `Seed point` in the largest vessel that must be enhanced.
3. Click `Preview` and check the result in the slice views. The preview is computed only in a small region around the seed point, so it updates quickly while parameters are being adjusted.
4. By default, `Compute vessel diameters and contrast from seed point` is enabled in the *Advanced* section, and the diameter and contrast values are estimated automatically from the image around the seed point. If the automatic values do not enhance the vessels well, release that toggle and set the values manually (they are disabled while the toggle is pressed).
5. When the preview looks good, click `Start` to filter the whole input volume. `Restore Defaults` resets all parameters.

## Parameters

All parameters below are in the *Advanced* section. `Minimum vessel diameter`, `Maximum vessel diameter`, and `Vessel contrast` are only editable when the `Compute vessel diameters and contrast from seed point` toggle is released.

- `Preview volume` and `Preview volume size`: the node that receives the quick preview and the size (in voxels) of the region around the seed point where it is computed. Use a small size while tuning parameters.
- `Display threshold`: only affects how the preview is displayed (which vesselness values are shown as opaque), not the computation.
- `Minimum vessel diameter` and `Maximum vessel diameter`: the range of diameters to enhance, **specified in voxels**. The module converts them to physical units internally by multiplying with the smallest voxel spacing of the input volume, so the values depend on image resolution. For example, in a coronary CTA with 0.37 mm in-plane spacing, a 1.0-5.0 mm diameter range corresponds to roughly 3-14 voxels. Structures outside the range are attenuated, so the maximum diameter should be somewhat larger than the largest vessel of interest.
- `Vessel contrast`: how much brighter the vessel is than the surrounding tissue. Lower values make the filter more sensitive, which enhances more structures but also more noise; higher values restrict the response to strongly contrasted vessels.
- `Suppress plates`: how strongly sheet-like structures (bone surfaces, vessel walls seen tangentially) are suppressed.
- `Suppress blobs`: how strongly blob-like structures (calcifications, small bright spots) are suppressed.

## Tips

- If thin distal branches disappear, decrease the minimum diameter and decrease `Vessel contrast`.
- If bone or contrast-filled cavities are enhanced together with the vessels, increase `Suppress plates` and `Suppress blobs`, or reduce the maximum diameter.
- The vesselness volume is only used to *initialize* the segmentation in the Level Set Segmentation module; the surface evolution is always performed on the original image, so a slightly imperfect vesselness volume is usually not a problem.

## References

- Sato, Y. et al. "Three-dimensional multi-scale line filter for segmentation and visualization of curvilinear structures in medical images". *Medical Image Analysis*, 1998, 2(2), 143-168.
- Antiga, L. et al. "An image-based modeling framework for patient-specific computational hemodynamics". *Medical & Biological Engineering & Computing*, 2008, 46, 1097-1112.
