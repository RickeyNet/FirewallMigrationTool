# FortiGate to Cisco FTD Configuration Converter - MAIN SCRIPT
# =============================================================
# This is the main script that orchestrates the conversion process.
# It loads the YAML file, calls the converter modules, and saves the output.

# This modular approach keeps the code organized and easier to maintain.

# REQUIREMENTS:
#     - Python 3.6 or higher
#     - PyYAML library (install with: pip install pyyaml)

# FILE STRUCTURE:
#     fortigate_converter.py          <- This main script (run this one!)
#     address_converter.py            <- Handles address object conversion
#     address_group_converter.py      <- Handles address group conversion
#     your_fortigate_config.yaml      <- Your FortiGate configuration file

# HOW TO RUN THIS SCRIPT:
#     1. Save ALL THREE Python files in the same folder
#     2. Place your FortiGate YAML file in the SAME FOLDER
#     3. Open terminal/command prompt and navigate to the folder:
#        cd C:\path\to\your\folder
#     4. Run the main script:
#        python fortigate_converter.py your_fortigate_config.yaml
    
#     EXAMPLES:
#     python fortigate_converter.py fortigate.yaml
#     python fortigate_converter.py fortigate.yaml -o output.json --pretty
#!/usr/bin/env python3

import yaml
import json
import argparse
import sys
from pathlib import Path

# Import our custom converter modules
# These modules contain the logic for converting specific object types
try:
    from address_converter import AddressConverter
    from address_group_converter import AddressGroupConverter
except ImportError as e:
    print("\n" + "="*60)
    print("ERROR: Missing converter module files!")
    print("="*60)
    print(f"\nDetails: {e}")
    print("\nMake sure these files are in the same folder as this script:")
    print("  1. address_converter.py")
    print("  2. address_group_converter.py")
    print("  3. fortigate_converter.py (this file)")
    print("\n" + "="*60)
    sys.exit(1)


def main():
    """
    Main function that orchestrates the entire conversion process.
    
    WORKFLOW:
    1. Parse command-line arguments (input file, output file, formatting)
    2. Load and parse the FortiGate YAML configuration file
    3. Initialize converter modules for each object type
    4. Convert address objects
    5. Convert address groups
    6. Combine all converted objects into one JSON structure
    7. Save the output JSON file
    8. Display a summary of what was converted
    
    Returns:
        0 on success, 1 on error
    """
    # ========================================================================
    # STEP 1: Set up command-line argument parser
    # ========================================================================
    # This allows users to customize how they run the script
    parser = argparse.ArgumentParser(
        description='Convert FortiGate YAML configuration to Cisco FTD FDM API JSON format',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python fortigate_converter.py fortigate.yaml
  python fortigate_converter.py fortigate.yaml -o output.json
  python fortigate_converter.py fortigate.yaml --pretty
  python fortigate_converter.py C:\\configs\\fortigate.yaml -o C:\\output\\ftd.json --pretty
        """
    )
    
    # REQUIRED argument: The FortiGate YAML file to convert
    parser.add_argument('input_file', 
                       help='Path to FortiGate YAML configuration file')
    
    # OPTIONAL argument: Where to save the output JSON (default: ftd_config.json)
    parser.add_argument('-o', '--output', 
                       help='Output JSON file path (default: ftd_config.json)',
                       default='ftd_config.json')
    
    # OPTIONAL flag: Make the JSON output human-readable with indentation
    parser.add_argument('-p', '--pretty', 
                       action='store_true',
                       help='Format JSON output with indentation for readability')
    
    # Parse the arguments that the user provided
    args = parser.parse_args()
    
    # ========================================================================
    # STEP 2: Display welcome banner
    # ========================================================================
    print("="*60)
    print("FortiGate to Cisco FTD Configuration Converter")
    print("="*60)
    
    # ========================================================================
    # STEP 3: Load the FortiGate YAML configuration file
    # ========================================================================
    print(f"\nLoading FortiGate configuration from: {args.input_file}")
    
    try:
        # Open the YAML file in read mode
        with open(args.input_file, 'r') as f:
            # Parse the YAML content into a Python dictionary
            # yaml.safe_load() safely parses YAML without executing code
            fg_config = yaml.safe_load(f)
        
        print("✓ YAML file loaded successfully")
        
    except FileNotFoundError:
        # This error occurs if the file doesn't exist at the specified path
        print(f"\n✗ ERROR: Input file '{args.input_file}' not found!")
        print("\nTroubleshooting:")
        print("  1. Check that the file path is correct")
        print("  2. If the file is in the same folder as this script, just use the filename")
        print("  3. If the file is elsewhere, provide the full path:")
        print("     Windows: C:\\path\\to\\file.yaml")
        print("     Mac/Linux: /path/to/file.yaml")
        return 1
        
    except yaml.YAMLError as e:
        # This error occurs if the YAML file has syntax errors
        print(f"\n✗ ERROR: Could not parse YAML file!")
        print(f"  Details: {e}")
        print("\nMake sure the file is valid YAML format")
        return 1
        
    except Exception as e:
        # Catch any other unexpected errors
        print(f"\n✗ ERROR: {e}")
        return 1
    
    # ========================================================================
    # STEP 4: Initialize converter modules
    # ========================================================================
    # Each converter module is responsible for one type of object
    print("\nInitializing converters...")
    
    # Create an AddressConverter instance with the FortiGate config
    address_converter = AddressConverter(fg_config)
    
    # Create an AddressGroupConverter instance with the FortiGate config
    address_group_converter = AddressGroupConverter(fg_config)
    
    # ========================================================================
    # STEP 5: Convert address objects
    # ========================================================================
    print("\n" + "-"*60)
    print("Converting Address Objects...")
    print("-"*60)
    
    # Call the convert() method to transform FortiGate addresses to FTD format
    # This returns a list of FTD network object dictionaries
    network_objects = address_converter.convert()
    
    print(f"✓ Converted {len(network_objects)} address objects")
    
    # ========================================================================
    # STEP 6: Convert address groups
    # ========================================================================
    print("\n" + "-"*60)
    print("Converting Address Groups...")
    print("-"*60)
    
    # Call the convert() method to transform FortiGate address groups to FTD format
    # This returns a list of FTD network group dictionaries
    network_groups = address_group_converter.convert()
    
    print(f"✓ Converted {len(network_groups)} address groups")
    
    # ========================================================================
    # STEP 7: Combine all converted objects into final structure
    # ========================================================================
    # This is the final JSON structure that will be saved to the output file
    # It's organized by object type for easy API consumption
    ftd_config = {
        "network_objects": network_objects,      # Individual address objects
        "network_groups": network_groups,        # Address groups
        # Future object types can be added here:
        # "port_objects": [],
        # "port_groups": [],
        # "access_policies": [],
    }
    
    # ========================================================================
    # STEP 8: Write the output JSON file
    # ========================================================================
    print(f"\n" + "-"*60)
    print(f"Saving output to: {args.output}")
    print("-"*60)
    
    try:
        # Open the output file in write mode
        with open(args.output, 'w') as f:
            if args.pretty:
                # Pretty print: Add indentation and newlines for readability
                # indent=2 means each level is indented by 2 spaces
                json.dump(ftd_config, f, indent=2)
            else:
                # Compact format: No extra whitespace, smaller file size
                json.dump(ftd_config, f)
        
        print("✓ JSON file created successfully")
        
    except IOError as e:
        # This error occurs if we can't write to the output file
        # (e.g., no permission, disk full, invalid path)
        print(f"\n✗ ERROR: Could not write output file!")
        print(f"  Details: {e}")
        return 1
    
    # ========================================================================
    # STEP 9: Display final summary
    # ========================================================================
    print("\n" + "="*60)
    print("CONVERSION COMPLETE")
    print("="*60)
    print(f"\nSummary:")
    print(f"  Network Objects:    {len(network_objects)}")
    print(f"  Network Groups:     {len(network_groups)}")
    print(f"\nOutput saved to: {args.output}")
    print("\nNext steps:")
    print("  1. Review the generated JSON file")
    print("  2. Test with a small subset first")
    print("  3. Use FTD FDM API to import the objects")
    print("  4. Verify the configuration in FTD")
    print("\n" + "="*60)
    
    return 0


# This is the entry point of the script
# When you run "python fortigate_converter.py", execution starts here
if __name__ == '__main__':
    sys.exit(main())