"""Naming a clip point from the panel.

A clip point's label is the name its cap carries downstream, so this box is where the naming of
a case happens - before meshing rather than after it, which is the point of it: the alternative
is right-click-rename on each point, and on a case with two dozen vessel ends that is most of
the work. What has to hold is that the box names the point the operator selected and no other,
and that it never quietly unnames one.
"""

import unittest

import slicer

from ClipVessel import _DEFAULT_CLIP_POINT_NAMES, _CLIP_POINT_NAME_LIST_PARAMETER
from ClipVesselTestFixture import clipVesselModuleWidget


class ClipPointNamesTest(unittest.TestCase):

    def setUp(self):
        slicer.mrmlScene.Clear()
        self.widget = clipVesselModuleWidget()
        # Slicer owns one widget per module and hands back the same one every time, so the
        # selection a previous test left on it outlives the scene being cleared. Put it back to
        # nothing selected, or a test that expects no selection inherits the last one's.
        self.widget._activeClipPointIndex = -1
        self.widget._activeClipPointId = None
        self.widget._planeEditing = False
        self.widget.updateManualPlaneButtonStates()
        self.clipPoints = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsFiducialNode",
                                                             "Clip points")
        for label in ("Inlet", "Outlet 1", "Outlet 2"):
            index = self.clipPoints.AddControlPoint([0.0, 0.0, 0.0])
            self.clipPoints.SetNthControlPointLabel(index, label)
        self.widget._parameterNode.SetNodeReferenceID("ClipPoints", self.clipPoints.GetID())

    def select(self, index):
        """Select a clip point, as clicking one in a 3D view does."""
        self.widget._activeClipPointIndex = index
        self.widget._activeClipPointId = self.clipPoints.GetNthControlPointID(index)
        self.widget._planeEditing = True
        self.widget.updateManualPlaneButtonStates()

    def labels(self):
        return [self.clipPoints.GetNthControlPointLabel(i) for i in range(3)]

    def test_the_box_is_offered_only_for_a_selected_point(self):
        """Disabled until a point is selected, and cleared again when the selection ends.

        The box holds the selected point's own name rather than a name waiting to be applied, so
        leaving the last point's name in it against no selection - or against a different point -
        would be an invitation to rename the wrong vessel.
        """
        combo = self.widget.ui.clipPointNameComboBox
        self.assertFalse(combo.enabled)

        self.select(1)
        self.assertTrue(combo.enabled)
        self.assertEqual(combo.currentText, "Outlet 1")

        self.select(2)
        self.assertEqual(combo.currentText, "Outlet 2")

        self.widget.finishPlaneEditing()
        self.assertFalse(combo.enabled)
        self.assertEqual(combo.currentText, "")

    def test_the_list_offers_the_built_in_names(self):
        combo = self.widget.ui.clipPointNameComboBox
        offered = [combo.itemText(index) for index in range(combo.count)]
        self.assertEqual(offered[:len(_DEFAULT_CLIP_POINT_NAMES)], list(_DEFAULT_CLIP_POINT_NAMES))

    def test_picking_a_name_renames_that_point_and_no_other(self):
        combo = self.widget.ui.clipPointNameComboBox
        self.select(1)
        index = combo.findText("RSVC")
        self.assertGreaterEqual(index, 0, "RSVC should be one of the built-in names")
        combo.currentIndex = index
        self.widget.onClipPointNameChosen(index)
        self.assertEqual(self.labels(), ["Inlet", "RSVC", "Outlet 2"])

    def test_a_typed_name_is_kept_and_offered_again(self):
        """A vocabulary is built once rather than retyped.

        The trunk names recur across cases, and a name already used on this anatomy is the one
        most likely to be wanted again. Saved on the parameter node, so it comes back with the
        scene.
        """
        combo = self.widget.ui.clipPointNameComboBox
        self.select(1)
        combo.currentText = "lpa_a"
        self.widget.onClipPointNameChosen()

        self.assertEqual(self.labels(), ["Inlet", "lpa_a", "Outlet 2"])
        self.assertGreaterEqual(combo.findText("lpa_a"), 0)
        self.assertIn("lpa_a",
                      self.widget._parameterNode.GetParameter(_CLIP_POINT_NAME_LIST_PARAMETER))

        # Offered once, not once per use.
        self.select(2)
        combo.currentText = "lpa_a"
        self.widget.onClipPointNameChosen()
        offered = [combo.itemText(index) for index in range(combo.count)]
        self.assertEqual(offered.count("lpa_a"), 1)

    def test_an_empty_box_does_not_unname_a_point(self):
        """Clearing the box happens on every selection change, so it cannot mean "remove the
        name" - a point with no label at all is one whose cap arrives unnamed downstream."""
        combo = self.widget.ui.clipPointNameComboBox
        self.select(0)
        combo.currentText = ""
        self.widget.onClipPointNameChosen()
        self.assertEqual(self.labels(), ["Inlet", "Outlet 1", "Outlet 2"])

    def test_nothing_is_renamed_with_no_point_selected(self):
        """The handler is reachable while nothing is being edited - the line edit emits
        editingFinished on focus loss - and must do nothing then."""
        self.widget.ui.clipPointNameComboBox.currentText = "RSVC"
        self.widget.onClipPointNameChosen()
        self.assertEqual(self.labels(), ["Inlet", "Outlet 1", "Outlet 2"])

    def test_capping_the_output_is_off_by_default(self):
        """The usual next step makes the caps itself, past a boundary layer, where they belong.

        Checked here because the checkbox and the parameter node used to disagree: the box was
        drawn unchecked and the default said true, so what the panel showed was not what a run
        would do.
        """
        self.assertEqual(self.widget._parameterNode.GetParameter("CapOutputSurface"), "false")
        self.assertFalse(self.widget.ui.capOutputSurfaceModelCheckBox.checked)


if __name__ == "__main__":
    # Run by slicer_add_python_test as "Slicer --python-script", which reports the outcome through
    # the exit code: an exception fails the test, a clean return passes it. unittest.main() is not
    # used because it exits the interpreter itself, taking Slicer down before it can report.
    import sys
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise AssertionError("%d failure(s) and %d error(s) in %d test(s)"
                             % (len(result.failures), len(result.errors), result.testsRun))
